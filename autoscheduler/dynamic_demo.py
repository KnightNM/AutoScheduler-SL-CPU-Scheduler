"""One-command Dynamic V3 training, selection, and unseen-workload demonstration."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from statistics import mean

from autoscheduler.dataset import save_dataset
from autoscheduler.dynamic import (
    DYNAMIC_FEATURE_NAMES,
    DynamicRouterConfig,
    RoutingDecision,
    generate_dynamic_workload,
    run_dynamic,
)
from autoscheduler.dynamic_training import build_training_data, prepare_validation, validation_metrics
from autoscheduler.evaluation import ALGORITHMS, DEPLOYABLE_ALGORITHMS, compare_algorithms, score_result_against_reference
from autoscheduler.fairness import aggregate_fairness
from autoscheduler.model import PolicyCostModel, _score_column, load_model, train_model
from autoscheduler.model_bakeoff import _new_model, candidate_configurations
from autoscheduler.real_config import load_real_config


def require_fresh_paths(output: Path, artifacts: Path) -> None:
    """Protect previous evidence from accidental overwrite."""
    for path in (output, artifacts):
        if path.exists() and any(path.iterdir()):
            raise ValueError(f"use fresh output paths; {path} is not empty")


def select_family(records: list[dict], simplicity: tuple[str, ...]) -> dict:
    """Choose validation winner; near-ties within 0.5% prefer simpler family."""
    selected = None
    for record in records:
        if selected is None:
            selected = record
            continue
        scale = max(abs(record["validation_score"]), abs(selected["validation_score"]), 1e-12)
        tied = abs(record["validation_score"] - selected["validation_score"]) <= scale * 0.005
        if (tied and simplicity.index(record["family"]) < simplicity.index(selected["family"])) or (
            not tied and record["validation_score"] < selected["validation_score"]
        ):
            selected = record
    return selected


def decision_rows(initial_policy: str, decisions: list[RoutingDecision]) -> list[dict]:
    active = initial_policy
    rows = []
    for decision in decisions:
        rows.append({
            "tick": decision.time,
            "active_before": active,
            "proposed": decision.selected,
            "confidence": decision.confidence,
            "accepted": decision.accepted,
            "reason": decision.reason,
            "active_after": decision.active,
            "decision_ms": decision.transition_ms,
            **decision.features,
        })
        active = decision.active
    return rows


def _partition(rows: list[dict], groups: dict[str, list[int]], name: str) -> list[dict]:
    seeds = set(groups[name])
    return [row for row in rows if row["seed"] in seeds]


def _xy(rows: list[dict], policies: tuple[str, ...]):
    return (
        [[row[name] for name in DYNAMIC_FEATURE_NAMES] for row in rows],
        [[row[_score_column(policy)] for policy in policies] for row in rows],
    )


def _multioutput_model(family: str, settings: dict, seed: int):
    model = _new_model(family, settings, seed)
    if family == "Histogram Gradient Boosting":
        from sklearn.multioutput import MultiOutputRegressor

        return MultiOutputRegressor(model)
    return model


def _row_regret(actual: list[list[float]], predicted) -> float:
    regrets = []
    for costs, estimates in zip(actual, predicted):
        selected = min(range(len(estimates)), key=lambda index: (estimates[index], index))
        regrets.append(costs[selected] - min(costs))
    return mean(regrets)


def _runtime_model(regressor, policies: tuple[str, ...], config: DynamicRouterConfig):
    model = PolicyCostModel(regressor, policies)
    model.dynamic_config_ = config.__dict__
    model.priority_rr_config_ = dict(ALGORITHMS["Priority RR"][1])
    model.policy_set_ = policies
    return model


def run_family_bakeoff(rows: list[dict], occupancy: dict, cases, config: DynamicRouterConfig,
                       seed: int, model_config: dict) -> tuple[list[dict], dict]:
    """Compare equal-budget policy-cost model families on the same grouped rows."""
    policies = tuple(DEPLOYABLE_ALGORITHMS)
    train_rows = _partition(rows, occupancy["groups"], "train")
    validation_rows = _partition(rows, occupancy["groups"], "validation")
    test_rows = _partition(rows, occupancy["groups"], "test")
    train_x, train_y = _xy(train_rows, policies)
    validation_x, validation_y = _xy(validation_rows, policies)
    test_x, test_y = _xy(test_rows, policies)
    results = []
    for family, settings_list in candidate_configurations(model_config).items():
        candidates = []
        for settings in settings_list:
            regressor = _multioutput_model(family, settings, seed).fit(train_x, train_y)
            regret = _row_regret(validation_y, regressor.predict(validation_x))
            candidates.append((regret, settings))
        validation_regret, settings = min(candidates, key=lambda item: item[0])
        regressor = _multioutput_model(family, settings, seed).fit(
            train_x + validation_x, train_y + validation_y
        )
        workload_metrics = validation_metrics(_runtime_model(regressor, policies, config), cases, config)
        results.append({
            "family": family,
            "settings": settings,
            "validation_action_regret": validation_regret,
            "validation_score": workload_metrics["validation_schedule_score"],
            "validation_p95_response": workload_metrics["validation_schedule_p95_response"],
            "validation_starvation": workload_metrics["validation_schedule_starvation"],
            "internal_test_action_regret": _row_regret(test_y, regressor.predict(test_x)),
        })
    selected = select_family(results, tuple(model_config["simplicity_order"]))
    return results, selected


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _save_gantt(path: Path, timeline: list[tuple[str, int, int]]) -> None:
    import os
    import tempfile

    cache = Path(tempfile.gettempdir()) / "autoscheduler-matplotlib"
    cache.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(cache))
    os.environ.setdefault("XDG_CACHE_HOME", str(cache))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    processes = list(dict.fromkeys(pid for pid, _, _ in timeline))
    positions = {pid: index for index, pid in enumerate(processes)}
    figure, axis = plt.subplots(figsize=(12, max(3, len(processes) * 0.28)))
    for pid, start, end in timeline:
        axis.barh(positions[pid], end - start, left=start, height=0.7)
    axis.set_yticks(range(len(processes)), processes)
    axis.set_xlabel("Simulation ticks")
    axis.set_title("Dynamic V3 unseen changing-workload Gantt chart")
    axis.grid(axis="x", alpha=0.25)
    figure.tight_layout()
    figure.savefig(path, dpi=160)
    plt.close(figure)


def _simulation_metrics(result, references) -> dict:
    fairness = aggregate_fairness(result.process_metrics)
    return {
        "weighted_score": score_result_against_reference(result, references),
        "mean_wait": result.avg_waiting_time,
        "mean_response": result.avg_response_time,
        "mean_turnaround": result.avg_turnaround_time,
        "p95_wait": fairness["p95_waiting_time"],
        "starvation_count": fairness["starvation_count"],
        "cpu_utilization": result.cpu_utilization,
        "throughput": result.throughput,
        "context_switches": result.context_switches,
        "makespan": result.makespan,
    }


def _write_report(path: Path, summary: dict) -> None:
    family_rows = "\n".join(
        f"| {row['family']} | {row['validation_score']:.6f} | {row['validation_action_regret']:.6f} | {row['internal_test_action_regret']:.6f} |"
        for row in summary["model_family_bakeoff"]
    )
    variant_rows = "\n".join(
        f"| {name} | {metrics['validation_schedule_score']:.6f} | {metrics['validation_schedule_p95_response']:.3f} | {metrics['validation_schedule_starvation']:.3f} |"
        for name, metrics in summary["tree_variants"].items()
    )
    live_rows = "\n".join(
        f"| {name} | {metrics['weighted_score']:.6f} | {metrics['mean_response']:.3f} | {metrics['p95_wait']:.3f} | {metrics['starvation_count']} |"
        for name, metrics in summary["unseen_workload"]["results"].items()
    )
    path.write_text(f"""# Dynamic V3 end-to-end demonstration

Status: **SYNTHETIC_DEVELOPMENT_ONLY**. This demonstrates the complete control flow; it is not Linux-kernel performance evidence.

## 1. Model-family bake-off

All families receive the same observed-state features, grouped trace split, policy-cost targets, and configuration budget. Lower is better. A result within 0.5% uses the configured simpler-family tie-break.

| Family | Validation schedule score | Validation action regret | Internal test action regret |
|---|---:|---:|---:|
{family_rows}

Selected family: **{summary['selected_family']}**. Decision Tree best under this run: **{summary['decision_tree_best']}**.
If this value is false, the run does not prove that Decision Tree is the best family; the tree-only Dynamic V3 stage below remains a workflow demonstration.

## 2. Dynamic V3 tree formulation

| Tree | Validation score | P95 response | Starvation |
|---|---:|---:|---:|
{variant_rows}

Frozen Dynamic V3 demonstration tree: **{summary['selected_tree_variant']}**.

## 3. Unseen changing workload

Seed: `{summary['unseen_workload']['seed']}`. Phases: `{', '.join(summary['unseen_workload']['phase_profiles'])}`.
The router schedules a review every 10 ticks and applies it at the next safe dispatch boundary. A switch must pass confidence, minimum 20-tick dwell, and policy-cost margin checks.

| Policy | Weighted score | Mean response | P95 wait | Starvation |
|---|---:|---:|---:|---:|
{live_rows}

Dynamic final policy: **{summary['unseen_workload']['final_policy']}**. Accepted switches: **{summary['unseen_workload']['accepted_switches']}**. Decision P99: **{summary['unseen_workload']['decision_p99_ms']:.6f} ms**.

## Artifacts

- `summary.json`: complete machine-readable report
- `model_family_bakeoff.csv`: five-family comparison
- `tree_variant_comparison.json`: classifier tree versus policy-cost tree
- `decision_log.csv`: every 10-tick review and safety decision
- `gantt.png`: final CPU execution timeline
- `{summary['artifacts']}/models/`: frozen classifier and policy-cost tree bundles
""", encoding="utf-8")


def run(output: Path, artifacts: Path, train_traces: int = 144, validation_traces: int = 60,
        train_seed: int = 7301, validation_seed: int = 7302, demo_seed: int = 9090,
        config_path: str | Path = "configs/real_desktop_ml.json") -> dict:
    require_fresh_paths(output, artifacts)
    if len({train_seed, validation_seed, demo_seed}) != 3:
        raise ValueError("training, validation, and unseen demo seeds must differ")
    output.mkdir(parents=True, exist_ok=True)
    artifacts.mkdir(parents=True, exist_ok=True)
    config = DynamicRouterConfig(
        epoch_ticks=10, dwell_epochs=2, confidence_threshold=0.8,
        initial_policy="MLFQ", fallback_policy="MLFQ",
    )

    print("[1/4] Building grouped Dynamic V3 training rows", flush=True)
    rows, occupancy = build_training_data(
        train_traces, train_seed, config, artifacts / "split.json", development=True
    )
    save_dataset(rows, artifacts / "training.csv")
    cases, validation = prepare_validation(validation_traces, validation_seed, config, development=True)

    print("[2/4] Comparing Dummy, Ridge, Decision Tree, Random Forest, and Histogram Gradient Boosting", flush=True)
    model_config = load_real_config(config_path)["models"]
    family_results, selected_family = run_family_bakeoff(
        rows, occupancy, cases, config, train_seed, model_config
    )
    _write_csv(output / "model_family_bakeoff.csv", family_results)

    print("[3/4] Comparing classifier tree with policy-cost tree", flush=True)
    models, reports, tree_metrics = {}, {}, {}
    for kind in ("classifier", "policy_cost"):
        model_path = artifacts / "models" / kind / "model.joblib"
        reports[kind] = train_model(
            rows, model_path, train_seed, feature_names=DYNAMIC_FEATURE_NAMES,
            metadata={"dynamic_config": config.__dict__, "static_baseline": validation["static_baseline"]},
            model_kind=kind,
            scheduler_validation=lambda candidate: validation_metrics(candidate, cases, config),
        )
        models[kind] = load_model(model_path, DYNAMIC_FEATURE_NAMES, expected_dynamic_config=config)
        tree_metrics[kind] = validation_metrics(models[kind], cases, config)
        _write_json(output / f"{kind}_training.json", reports[kind])
    selected_tree = min(tree_metrics, key=lambda name: (tree_metrics[name]["validation_schedule_score"], name))
    _write_json(output / "tree_variant_comparison.json", {
        "selected": selected_tree, "metrics": tree_metrics,
    })

    print("[4/4] Running frozen router on one unseen changing workload", flush=True)
    workload = generate_dynamic_workload(demo_seed)
    routed = run_dynamic(workload.processes, models[selected_tree], config)
    comparison = compare_algorithms(
        workload.processes, algorithms=tuple(dict.fromkeys((*ALGORITHMS, *DEPLOYABLE_ALGORITHMS)))
    )
    references = {name: comparison[name] for name in ALGORITHMS}
    result_metrics = {name: _simulation_metrics(result, references) for name, result in comparison.items()}
    result_metrics["Dynamic V3"] = _simulation_metrics(routed.simulation, references)
    decisions = decision_rows(routed.initial_policy, routed.decisions)
    _write_csv(output / "decision_log.csv", decisions)
    _save_gantt(output / "gantt.png", routed.simulation.timeline)

    summary = {
        "status": "SYNTHETIC_DEVELOPMENT_ONLY",
        "router": config.__dict__,
        "training": {"seed": train_seed, "traces": train_traces, "rows": len(rows), "split": occupancy},
        "validation": {"seed": validation_seed, "traces": validation_traces},
        "model_family_bakeoff": family_results,
        "selected_family": selected_family["family"],
        "decision_tree_best": selected_family["family"] == "Decision Tree",
        "tree_variants": tree_metrics,
        "selected_tree_variant": selected_tree,
        "artifacts": str(artifacts),
        "unseen_workload": {
            "seed": demo_seed,
            "phase_profiles": list(workload.phase_profiles),
            "processes": len(workload.processes),
            "initial_policy": routed.initial_policy,
            "final_policy": routed.final_policy,
            "reviews": len(routed.decisions),
            "accepted_switches": sum(decision.accepted for decision in routed.decisions),
            "decision_p99_ms": routed.transition_p99_ms,
            "results": result_metrics,
        },
    }
    _write_json(output / "summary.json", summary)
    _write_report(output / "REPORT.md", summary)
    print(f"Selected family: {summary['selected_family']}")
    print(f"Frozen Dynamic V3 tree: {selected_tree}")
    print(f"Unseen workload phases: {', '.join(workload.phase_profiles)}")
    print(f"Accepted switches: {summary['unseen_workload']['accepted_switches']}")
    print(f"Decision P99: {routed.transition_p99_ms:.6f} ms")
    print(f"Report: {output / 'REPORT.md'}")
    return summary
