"""Prototype action-cost model bake-off for cleaned real-trace rows."""

from __future__ import annotations

import csv
import json
import math
import random
import time
from collections import defaultdict
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable

from autoscheduler.model_bakeoff import _new_model, run_bakeoff
from autoscheduler.real_features import FEATURE_NAMES
from autoscheduler.real_split import split_feature_rows


def _action_feature_name(action: str) -> str:
    return "action_" + "".join(character.lower() if character.isalnum() else "_" for character in action).strip("_")


def _snapshot_key(row: dict[str, Any]) -> tuple[str, str]:
    return str(row["trace_id"]), str(row["decision_timestamp_ns"])


def _validate_rows(rows: list[dict[str, Any]], actions: tuple[str, ...]) -> str:
    if not rows:
        raise ValueError("action-cost rows cannot be empty")
    provenances = {row.get("label_provenance") for row in rows}
    if len(provenances) != 1 or None in provenances or "" in provenances:
        raise ValueError("bake-off requires one label provenance")
    snapshots: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in rows:
        snapshots[_snapshot_key(row)].add(str(row.get("action", "")))
    if any(found != set(actions) for found in snapshots.values()):
        raise ValueError("each observed state requires exactly one cost row per deployable action")
    return str(next(iter(provenances)))


def _encode_actions(rows: Iterable[dict[str, Any]], actions: tuple[str, ...]) -> list[dict[str, Any]]:
    action_features = {_action_feature_name(action): action for action in actions}
    return [{
        **row,
        **{name: float(row["action"] == action) for name, action in action_features.items()},
    } for row in rows]


def _realized_cost(rows: list[dict[str, Any]], predictions: list[float]) -> float:
    """Use each model's selected action, then look up its observed replay cost."""
    choices: dict[tuple[str, str], tuple[float, str, float]] = {}
    for row, prediction in zip(rows, predictions):
        choice = (float(prediction), str(row["action"]), float(row["policy_cost"]))
        key = _snapshot_key(row)
        if key not in choices or choice[:2] < choices[key][:2]:
            choices[key] = choice
    return fmean(choice[2] for choice in choices.values())


def _write_candidates(report: dict[str, Any], output: Path) -> None:
    rows = []
    selected = report["bakeoff"]["selected"]
    for family, candidates in report["bakeoff"]["families"].items():
        for candidate in candidates:
            rows.append({
                "family": family,
                "settings": json.dumps(candidate["settings"], sort_keys=True),
                "validation_realized_cost": candidate["validation_score"],
                "selected": candidate["family"] == selected["family"] and candidate["settings"] == selected["settings"],
            })
    with output.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=("family", "settings", "validation_realized_cost", "selected"))
        writer.writeheader()
        writer.writerows(rows)


def _comparison(rows: list[dict[str, Any]], actions: tuple[str, ...]) -> dict[str, Any]:
    by_action = {
        action: fmean(float(row["policy_cost"]) for row in rows if row["action"] == action)
        for action in actions
    }
    by_snapshot: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in rows:
        by_snapshot[_snapshot_key(row)].append(float(row["policy_cost"]))
    return {
        "locked_test_fixed_action_cost": by_action,
        "locked_test_oracle_cost": fmean(min(costs) for costs in by_snapshot.values()),
    }


def _prototype_sufficiency(
    splits: dict[str, list[dict[str, Any]]], group_by: tuple[str, ...]
) -> dict[str, Any]:
    group_counts = {
        name: len({tuple(row[field] for field in group_by) for row in rows})
        for name, rows in splits.items()
    }
    total_groups = sum(group_counts.values())
    sufficient = total_groups >= 15 and all(count >= 3 for count in group_counts.values())
    return {
        "status": "SUFFICIENT_FOR_PROTOTYPE_COMPARISON" if sufficient else "INSUFFICIENT_FOR_PROTOTYPE_COMPARISON",
        "data_sufficient": sufficient,
        "trace_group_counts": group_counts,
        "total_trace_groups": total_groups,
        "minimum_total_trace_groups": 15,
        "minimum_trace_groups_per_split": 3,
        "scope": "offline_replay_model_comparison_only",
    }
def _matrix(rows: list[dict[str, Any]], features: tuple[str, ...]) -> list[list[float]]:
    return [[float(row[name]) for name in features] for row in rows]


def _selected_costs(rows: list[dict[str, Any]], predictions: list[float]) -> dict[tuple[str, str], tuple[str, float]]:
    choices: dict[tuple[str, str], tuple[float, str, float]] = {}
    for row, prediction in zip(rows, predictions):
        candidate = (float(prediction), str(row["action"]), float(row["policy_cost"]))
        key = _snapshot_key(row)
        if key not in choices or candidate[:2] < choices[key][:2]:
            choices[key] = candidate
    return {key: (choice[1], choice[2]) for key, choice in choices.items()}


def _bootstrap_ci(differences: list[float], seed: int, samples: int = 10_000) -> tuple[float, float]:
    randomizer = random.Random(seed)
    means = sorted(fmean(randomizer.choice(differences) for _ in differences) for _ in range(samples))
    return means[math.floor((samples - 1) * 0.025)], means[math.floor((samples - 1) * 0.975)]


def _p99(values: list[float]) -> float:
    return sorted(values)[math.ceil(len(values) * 0.99) - 1]


def _model_comparison(
    splits: dict[str, list[dict[str, Any]]], encoded: dict[str, list[dict[str, Any]]], features: tuple[str, ...],
    bakeoff: dict[str, Any], config: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    train_rows = encoded["train"] + encoded["validation"]
    train_x, train_y = _matrix(train_rows, features), [float(row["policy_cost"]) for row in train_rows]
    test_x, test_y = _matrix(encoded["test"], features), [float(row["policy_cost"]) for row in encoded["test"]]
    action_rows = splits["test"]
    by_snapshot = defaultdict(list)
    for row in action_rows:
        by_snapshot[_snapshot_key(row)].append(row)
    oracle = {
        key: {row["action"] for row in group if float(row["policy_cost"]) == min(float(item["policy_cost"]) for item in group)}
        for key, group in by_snapshot.items()
    }
    report = {}
    for family, candidates in bakeoff["families"].items():
        candidate = min(candidates, key=lambda item: item["validation_score"])
        model = _new_model(family, candidate["settings"], config["seeds"]["model_tuning"])
        model.fit(train_x, train_y)
        predictions = list(model.predict(test_x))
        selections = _selected_costs(action_rows, predictions)
        residuals = [actual - predicted for actual, predicted in zip(test_y, predictions)]
        mean_target = fmean(test_y)
        denominator = sum((value - mean_target) ** 2 for value in test_y)
        matrices = [_matrix([row for row in encoded["test"] if _snapshot_key(row) == key], features) for key in selections]
        for matrix in matrices:
            model.predict(matrix)
        latencies = []
        for matrix in matrices:
            started = time.perf_counter_ns()
            model.predict(matrix)
            latencies.append((time.perf_counter_ns() - started) / 1_000_000)
        report[family] = {
            "settings": candidate["settings"],
            "validation_realized_cost": candidate["validation_score"],
            "locked_test_realized_cost": fmean(cost for _, cost in selections.values()),
            "test_cost_mae": fmean(abs(item) for item in residuals),
            "test_cost_r2": None if denominator == 0 else 1 - sum(item ** 2 for item in residuals) / denominator,
            "action_selection_accuracy": sum(action in oracle[key] for key, (action, _) in selections.items()) / len(selections),
            "decision_p99_ms": _p99(latencies),
            "selected": family == bakeoff["selected"]["family"] and candidate["settings"] == bakeoff["selected"]["settings"],
        }
    return report


def _locked_gates(
    splits: dict[str, list[dict[str, Any]]], encoded: dict[str, list[dict[str, Any]]], features: tuple[str, ...],
    actions: tuple[str, ...], config: dict[str, Any], bakeoff: dict[str, Any],
) -> dict[str, Any]:
    validation = splits["validation"]
    comparator = min(
        actions,
        key=lambda action: (fmean(float(row["policy_cost"]) for row in validation if row["action"] == action), actions.index(action)),
    )
    selected = bakeoff["selected"]
    train_rows = encoded["train"] + encoded["validation"]
    model = _new_model(selected["family"], selected["settings"], config["seeds"]["model_tuning"])
    model.fit(_matrix(train_rows, features), [float(row["policy_cost"]) for row in train_rows])
    test_rows = encoded["test"]
    selections = _selected_costs(splits["test"], list(model.predict(_matrix(test_rows, features))))
    baseline = {
        _snapshot_key(row): float(row["policy_cost"])
        for row in splits["test"] if row["action"] == comparator
    }
    differences = [selection[1] - baseline[key] for key, selection in selections.items()]
    selected_cost = fmean(selection[1] for selection in selections.values())
    baseline_cost = fmean(baseline.values())
    ci_low, ci_high = _bootstrap_ci(differences, config["seeds"]["bootstrap"])
    matrices = [_matrix([row for row in test_rows if _snapshot_key(row) == key], features) for key in selections]
    for matrix in matrices:
        model.predict(matrix)
    latencies = []
    for matrix in matrices:
        start = time.perf_counter_ns()
        model.predict(matrix)
        latencies.append((time.perf_counter_ns() - start) / 1_000_000)
    p99 = sorted(latencies)[math.ceil(len(latencies) * 0.99) - 1]
    expected_traces = math.ceil(config["data"]["configurations"] * config["data"]["repetitions_per_configuration"] * config["dataset"]["split"]["test"])
    trace_count = len({row["trace_id"] for row in splits["test"]})
    improvement = None if baseline_cost == 0 else (baseline_cost - selected_cost) / baseline_cost
    gates = config["acceptance_gates"]
    data_sufficient = trace_count >= expected_traces
    fairness = _fairness_gate(splits["test"], selections, comparator, gates)
    gate_results = {
        "improvement_gate": improvement is not None and improvement >= gates["minimum_mean_score_improvement_fraction"],
        "confidence_gate": ci_high < 0,
        "latency_gate": p99 < gates["decision_p99_ms_strictly_below"],
        "fairness_gate": fairness["passes"],
    }
    status = "INSUFFICIENT_DATA" if not data_sufficient else ("PASS" if all(value is True for value in gate_results.values()) else "FAIL")
    return {
        "status": status,
        "fixed_comparator": comparator,
        "locked_test_model_cost": selected_cost,
        "locked_test_comparator_cost": baseline_cost,
        "mean_improvement_fraction": improvement,
        "paired_difference_model_minus_comparator": {"mean": fmean(differences), "ci_low": ci_low, "ci_high": ci_high, "bootstrap_samples": 10_000},
        "decision_p99_ms": p99,
        "locked_test_trace_count": trace_count,
        "minimum_locked_test_trace_count": expected_traces,
        "data_sufficient": data_sufficient,
        "fairness": fairness,
        **gate_results,
    }


def _fairness_gate(
    rows: list[dict[str, Any]], selections: dict[tuple[str, str], tuple[str, float]], comparator: str, gates: dict[str, Any],
) -> dict[str, Any]:
    by_key = {(_snapshot_key(row), row["action"]): row for row in rows}
    pairs = [(by_key[(key, selected)], by_key[(key, comparator)]) for key, (selected, _) in selections.items()]
    required = ("starvation_count", "post_io_max_response_time")
    if any(field not in row for pair in pairs for row in pair for field in required):
        return {"passes": "UNAVAILABLE", "reason": "fairness labels are absent"}
    starvation_selected = fmean(float(pair[0]["starvation_count"]) for pair in pairs)
    starvation_baseline = fmean(float(pair[1]["starvation_count"]) for pair in pairs)
    response_pairs = [
        (float(pair[0]["post_io_max_response_time"]), float(pair[1]["post_io_max_response_time"]))
        for pair in pairs if pair[0]["post_io_max_response_time"] not in (None, "") and pair[1]["post_io_max_response_time"] not in (None, "")
    ]
    if not response_pairs:
        return {"passes": "UNAVAILABLE", "reason": "no post-I/O samples"}
    selected_response = fmean(pair[0] for pair in response_pairs)
    baseline_response = fmean(pair[1] for pair in response_pairs)
    response_passes = selected_response <= baseline_response * (1 + gates["maximum_p99_foreground_response_regression_fraction"])
    starvation_passes = starvation_selected <= starvation_baseline
    return {
        "passes": response_passes and starvation_passes,
        "selected_mean_starvation_count": starvation_selected,
        "comparator_mean_starvation_count": starvation_baseline,
        "selected_mean_post_io_max_response_time": selected_response,
        "comparator_mean_post_io_max_response_time": baseline_response,
    }


def _write_locked_evaluation_report(report: dict[str, Any], output: Path) -> None:
    gates = report["gates"]
    difference = gates["paired_difference_model_minus_comparator"]
    output.write_text("\n".join((
        "# Locked Evaluation Gate Report",
        "",
        f"**Status: {gates['status']}**",
        "",
        f"- Fixed comparator: `{gates['fixed_comparator']}` (chosen only from validation data)",
        f"- Locked-test traces: {gates['locked_test_trace_count']} / {gates['minimum_locked_test_trace_count']} required",
        f"- Model cost: `{gates['locked_test_model_cost']:.6f}`; comparator cost: `{gates['locked_test_comparator_cost']:.6f}`",
        f"- Improvement: `{gates['mean_improvement_fraction']}`; gate: `{gates['improvement_gate']}`",
        f"- Paired model-minus-comparator 95% CI: `[{difference['ci_low']:.6f}, {difference['ci_high']:.6f}]`; gate: `{gates['confidence_gate']}`",
        f"- Decision P99: `{gates['decision_p99_ms']:.6f} ms`; gate: `{gates['latency_gate']}`",
        f"- Fairness gate: `{gates['fairness_gate']}`; details: `{gates['fairness']}`",
        "",
        "This report is an offline replay prototype. It cannot authorize a scheduler deployment or support a real-kernel performance claim.",
        "",
    )), encoding="utf-8")
def _write_markdown_report(report: dict[str, Any], output: Path) -> None:
    selected = report["bakeoff"]["selected"]
    comparison = report["comparison"]
    rows = [
        "# Prototype Action-Cost Bake-off Report",
        "",
        "## Status",
        "",
        f"**{report['prototype_sufficiency']['status'].replace('_', ' ')}**",
        "",
        "Development-only offline replay screening. This is not evidence of Linux kernel scheduler performance.",
        "",
        "## Data",
        "",
        f"- Label provenance: `{report['label_provenance']}`",
        f"- Action rows (train / validation / locked test): {report['row_counts']['train']} / {report['row_counts']['validation']} / {report['row_counts']['test']}",
        f"- Traces (train / validation / locked test): {report['trace_counts']['train']} / {report['trace_counts']['validation']} / {report['trace_counts']['test']}",
        f"- Profiles: `{report['dataset']['profiles']}`",
        f"- Processes / events: {report['dataset']['process_count']} / {report['dataset']['event_count']}",
        f"- Seeds: `{report['dataset']['seeds']}`",
        "- Cleaning: completed traces are anonymized before feature extraction; action rows are group-split by application, scenario, and capture session.",
        "- Limitation: synthetic data tests the pipeline only and cannot establish a real scheduler result.",
        "",
        "## Feature method",
        "",
        "At each decision time, every feature is calculated only from events strictly before that time. The model receives these observed-history features plus a one-hot proposed action:",
        "",
        ", ".join(f"`{feature}`" for feature in FEATURE_NAMES) + ".",
        "",
        "## Selection",
        "",
        f"- Model: **{selected['family']}** with `{json.dumps(selected['settings'], sort_keys=True)}`",
        f"- Validation realized cost: `{selected['validation_score']:.6f}`",
        f"- Locked-test realized cost: `{selected['test_score']:.6f}`",
        "",
        "The model receives an observed state plus one proposed action, predicts that action's cost, then selects the action with the smallest prediction.",
        "",
        "## Locked-test comparators",
        "",
        "| Choice | Mean offline replay cost |",
        "| --- | ---: |",
    ]
    rows.extend(f"| Fixed {action} | {cost:.6f} |" for action, cost in comparison["locked_test_fixed_action_cost"].items())
    rows.extend((
        f"| Per-state oracle | {comparison['locked_test_oracle_cost']:.6f} |",
        f"| Selected {selected['family']} | {selected['test_score']:.6f} |",
        "",
        "## Model comparison",
        "",
        "Cost MAE and R² evaluate cost prediction. Action-selection accuracy is agreement with the lowest-cost action for each observed state; it is not a classifier training accuracy.",
        "",
        "| Model | Validation cost | Locked-test cost | Cost MAE | Cost R² | Oracle-action agreement | P99 ms | Selected |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ))
    rows.extend(
        f"| {family} | {metrics['validation_realized_cost']:.6f} | {metrics['locked_test_realized_cost']:.6f} | {metrics['test_cost_mae']:.6f} | {metrics['test_cost_r2'] if metrics['test_cost_r2'] is not None else 'n/a'} | {metrics['action_selection_accuracy']:.3f} | {metrics['decision_p99_ms']:.6f} | {'Yes' if metrics['selected'] else 'No'} |"
        for family, metrics in report["model_comparison"].items()
    )
    rows.extend((
        "",
        "## Interpretation",
        "",
        "This synthetic dataset exercises the full report pipeline. Its results are not a real-workload or Linux-kernel claim.",
        "",
    ))
    output.write_text("\n".join(rows), encoding="utf-8")


def run_prototype_bakeoff(rows: Iterable[dict[str, Any]], config: dict[str, Any], output: str | Path, traces: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Fit action-cost regressors and choose actions by lowest predicted cost."""
    rows = list(rows)
    actions = tuple(policy["name"] for policy in config["policies"]["deployable"])
    provenance = _validate_rows(rows, actions)
    dataset = config["dataset"]
    splits = split_feature_rows(rows, dataset["split"], tuple(dataset["group_by"]), config["seeds"]["split"])
    encoded = {name: _encode_actions(split, actions) for name, split in splits.items()}
    features = (*FEATURE_NAMES, *(_action_feature_name(action) for action in actions))
    bakeoff = run_bakeoff(
        encoded["train"], encoded["validation"], encoded["test"], features, "policy_cost",
        config["models"], config["seeds"]["model_tuning"], _realized_cost,
    )
    model_comparison = _model_comparison(splits, encoded, features, bakeoff, config)
    gates = _locked_gates(splits, encoded, features, actions, config, bakeoff)
    if provenance == "synthetic_development_only":
        gates["status"] = "SYNTHETIC_DEVELOPMENT_ONLY"
    report = {
        "status": "prototype_development_only",
        "label_provenance": provenance,
        "actions": list(actions),
        "selection_metric": "realized_cost_of_lowest_predicted_action_per_observed_state",
        "row_counts": {name: len(split) for name, split in splits.items()},
        "trace_counts": {name: len({row["trace_id"] for row in split}) for name, split in splits.items()},
        "prototype_sufficiency": _prototype_sufficiency(splits, tuple(dataset["group_by"])),
        "dataset": {
            "profiles": sorted({str(row.get("workload_family", "unknown")) for row in rows}),
            "process_count": sum(len(trace["processes"]) for trace in traces) if traces is not None else None,
            "event_count": sum(len(trace["events"]) for trace in traces) if traces is not None else None,
            "seeds": {**config["seeds"], "generation": sorted({trace["metadata"].get("generation_seed") for trace in traces if trace["metadata"].get("generation_seed") is not None}) if traces is not None else None},
        },
        "bakeoff": bakeoff,
        "model_comparison": model_comparison,
        "comparison": _comparison(splits["test"], actions),
        "gates": gates,
        "limitation": "Offline replay labels from pilot traces are not real kernel measurements and cannot select a final deployable model.",
    }
    root = Path(output)
    root.mkdir(parents=True, exist_ok=True)
    (root / "summary.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    _write_candidates(report, root / "candidates.csv")
    _write_markdown_report(report, root / "prototype_comparison_report.md")
    _write_locked_evaluation_report(report, root / "locked_evaluation_report.md")
    return report
