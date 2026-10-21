"""Corrective synthetic experiment. No real-data model selection or promotion."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
from itertools import product
import json
from pathlib import Path
from statistics import mean

from autoscheduler.dataset import save_dataset
from autoscheduler.dynamic import (
    DYNAMIC_FEATURE_NAMES, DynamicRouterConfig, _percentile, evaluate_dynamic,
    run_dynamic, save_dynamic_evaluation,
)
from autoscheduler.dynamic_training import build_training_data, prepare_validation, validation_metrics
from autoscheduler.evaluation import DEPLOYABLE_ALGORITHMS, score_result_against_reference
from autoscheduler.experiments import paired_bootstrap_ci
from autoscheduler.fairness import aggregate_fairness
from autoscheduler.model import load_model, train_model
from scheduler.mlfq import mlfq
from simulator.simulator import run_simulation


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tune_static(cases) -> tuple[dict, list[dict]]:
    """Same objective and cost; only development workloads choose parameters."""
    candidates = []
    for quanta, aging in product(((1, 2, 4), (2, 4, 8), (4, 8, 16)), (10, 20, 40)):
        parameters = {"quanta": quanta, "aging_threshold": aging, "context_switch_cost": 0}
        scores = [score_result_against_reference(run_simulation("Tuned MLFQ", mlfq, list(workload.processes), **parameters), refs)
                  for workload, _, refs in cases]
        candidates.append({"parameters": parameters, "validation_score": mean(scores)})
    return min(candidates, key=lambda candidate: candidate["validation_score"])["parameters"], candidates


def audit_cases(cases, models: dict, config, tuned: dict) -> tuple[list[dict], dict]:
    """Common, candidate-independent normalization; paired workload comparisons."""
    names = (*DEPLOYABLE_ALGORITHMS, "Tuned MLFQ", *models)
    rows, latencies = [], {family: [] for family in models}
    for workload, static, references in cases:
        simulations = {policy: static[policy] for policy in DEPLOYABLE_ALGORITHMS}
        simulations["Tuned MLFQ"] = run_simulation("Tuned MLFQ", mlfq, list(workload.processes), **tuned)
        routing = {}
        for family, model in models.items():
            result = run_dynamic(workload.processes, model, config)
            simulations[family] = result.simulation
            routing[family] = result
            latencies[family].extend(decision.transition_ms for decision in result.decisions)
        for name, result in simulations.items():
            row = {
                "seed": workload.seed, "family": getattr(workload, "family", "frozen_cohorts"),
                "policy": name, "score": score_result_against_reference(result, references),
                "p95_response": _percentile([metric.response_time for metric in result.process_metrics], .95),
                "starvation": aggregate_fairness(result.process_metrics)["starvation_count"],
                "switches": sum(decision.accepted for decision in routing[name].decisions) if name in routing else 0,
                "decision_p99_ms": routing[name].transition_p99_ms if name in routing else None,
            }
            rows.append(row)
    by_policy = {name: [row for row in rows if row["policy"] == name] for name in names}
    summaries = {}
    for name, records in by_policy.items():
        summary = {"mean_" + key: mean(row[key] for row in records)
                   for key in ("score", "p95_response", "starvation", "switches")}
        summary["mean_regret_to_best_static"] = mean(
            row["score"] - min(by_policy[policy][index]["score"] for policy in (*DEPLOYABLE_ALGORITHMS, "Tuned MLFQ"))
            for index, row in enumerate(records)
        )
        summary["by_family"] = {
            family: {"traces": len(group), **{"mean_" + key: mean(row[key] for row in group)
                     for key in ("score", "p95_response", "starvation", "switches")}}
            for family in sorted({row["family"] for row in records})
            for group in ([row for row in records if row["family"] == family],)
        }
        if name in models:
            summary["decision_p99_ms"] = _percentile(latencies[name], .99)
            summary["max_workload_decision_p99_ms"] = max(row["decision_p99_ms"] for row in records)
            summary["comparisons"] = {}
            for baseline in (*DEPLOYABLE_ALGORITHMS, "Tuned MLFQ"):
                differences = {key: [row[key] - base[key] for row, base in zip(records, by_policy[baseline])]
                               for key in ("score", "p95_response", "starvation")}
                summary["comparisons"][baseline] = {
                    key + "_difference": paired_bootstrap_ci(values) for key, values in differences.items()
                }
                summary["comparisons"][baseline].update(
                    wins=sum(value < -1e-12 for value in differences["score"]),
                    ties=sum(abs(value) <= 1e-12 for value in differences["score"]),
                    losses=sum(value > 1e-12 for value in differences["score"]),
                )
        summaries[name] = summary
    return rows, summaries


def save_audit(output: Path, rows, summary) -> None:
    _write(output / "summary.json", summary)
    with (output / "workloads.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run(output: Path, artifacts: Path, train_traces=144, validation_traces=60,
        development_audit_traces=120, frozen_traces=1000) -> dict:
    import platform
    import sklearn

    if (output / "protocol.json").exists() or (artifacts / "split.json").exists():
        raise ValueError("use fresh versioned output paths")
    config = DynamicRouterConfig(epoch_ticks=10, dwell_epochs=2, confidence_threshold=.8,
                                 initial_policy="MLFQ", fallback_policy="MLFQ")
    sources = [Path(path) for path in (
        "autoscheduler/dynamic.py", "autoscheduler/model.py", "autoscheduler/dynamic_training.py",
        "autoscheduler/development_workloads.py", "autoscheduler/dynamic_v3_experiment.py",
        "autoscheduler/evaluation.py", "simulator/engine.py", "configs/real_desktop_ml.json",
    )]
    protocol = {
        "status": "SYNTHETIC_DEVELOPMENT_ONLY", "config": config.__dict__,
        "train": {"traces": train_traces, "seed": 7301},
        "validation": {"traces": validation_traces, "seed": 7302},
        "development_audit": {"traces": development_audit_traces, "seed": 7303},
        "frozen_audit": {"traces": frozen_traces, "seed": 2026},
        "static_grid": {"quanta": [[1, 2, 4], [2, 4, 8], [4, 8, 16]], "aging": [10, 20, 40], "switch_cost": 0},
        "selection": "realized_validation_schedule_score_then_action_regret_then_simpler_tree",
        "normalization": "unchanged_six_static_policy_bounds", "cost_switch_margin": .005,
        "original_gates": "P95_vs_RR_CI_high<0; score_vs_RR_CI_high<=0; max_workload_routing_P99<10ms",
        "comparator_gates": "score_CI_high<0; response_CI_high<=0; mean_starvation<=baseline; original_latency",
        "promotion": "NEVER_SYNTHETIC_ONLY", "python": platform.python_version(), "sklearn": sklearn.__version__,
        "source_sha256": {str(path): _hash(path) for path in sources},
    }
    _write(output / "protocol.json", protocol)
    print("Building grouped development-only labels", flush=True)
    rows, occupancy = build_training_data(train_traces, 7301, config, artifacts / "split.json", development=True)
    save_dataset(rows, artifacts / "training.csv")
    cases, validation = prepare_validation(validation_traces, 7302, config, development=True)
    tuned, grid = tune_static(cases)
    _write(output / "static_tuning.json", {"parameters": tuned, "candidates": grid, "validation": validation})
    print(f"Static comparator: {validation['static_baseline']}; development MLFQ parameters {tuned}", flush=True)
    models, reports, metrics = {}, {}, {}
    for family in ("classifier", "policy_cost"):
        print(f"Selecting {family} trees by realized development scheduling", flush=True)
        path = artifacts / "candidates" / family / "model.joblib"
        reports[family] = train_model(
            rows, path, 7301, feature_names=DYNAMIC_FEATURE_NAMES,
            metadata={"dynamic_config": config.__dict__, "static_baseline": validation["static_baseline"],
                      "label_definition": "feasible_dwell_global_review_boundary_then_MLFQ_fixed_reference_advantage",
                      "training_suite": "six_development_families"},
            model_kind=family, scheduler_validation=lambda candidate: validation_metrics(candidate, cases, config),
        )
        models[family] = load_model(path, DYNAMIC_FEATURE_NAMES, expected_dynamic_config=config)
        metrics[family] = validation_metrics(models[family], cases, config)
        _write(output / f"{family}_training.json", reports[family])
    selected = min(metrics, key=lambda family: (metrics[family]["validation_schedule_score"], family))
    comparator_scores = {**validation["static_scores"], "Tuned MLFQ": min(candidate["validation_score"] for candidate in grid)}
    comparator = min(comparator_scores, key=comparator_scores.get)
    frozen_selection = {"selected": selected, "family_validation": metrics, "static_validation": validation,
                        "tuned_static_parameters": tuned, "comparison_baseline": comparator,
                        "comparison_validation_scores": comparator_scores}
    _write(output / "frozen_selection.json", frozen_selection)
    print(f"Frozen family: {selected}; evaluating development audit and untouched original traces", flush=True)
    development_cases, _ = prepare_validation(development_audit_traces, 7303, config, development=True)
    dev_rows, dev = audit_cases(development_cases, models, config, tuned)
    save_audit(output / "development_audit", dev_rows, dev)
    frozen_cases, _ = prepare_validation(frozen_traces, 2026, config)
    frozen_rows, frozen = audit_cases(frozen_cases, models, config, tuned)
    save_audit(output / "frozen_audit", frozen_rows, frozen)
    gates = {}
    for family, model in models.items():
        print(f"Recording original eligibility gates for {family}", flush=True)
        evaluation_rows, gates[family] = evaluate_dynamic(
            model, frozen_traces, 2026, config, frozen_static_baseline=validation["static_baseline"],
        )
        save_dynamic_evaluation(evaluation_rows, gates[family], output / family)
    acceptance = {}
    for family in models:
        comparisons = frozen[family]["comparisons"][comparator]
        acceptance[family] = {
            "original_gates": gates[family]["eligible"],
            "score_vs_development_selected_static": comparisons["score_difference"]["ci_high"] < 0,
            "p95_vs_development_selected_static": comparisons["p95_response_difference"]["ci_high"] <= 0,
            "starvation_vs_development_selected_static": comparisons["starvation_difference"]["mean"] <= 0,
            "latency_all_recorded_passes": gates[family]["latency_gate"] and all(
                suite[family]["max_workload_decision_p99_ms"] < 10 for suite in (dev, frozen)),
        }
        acceptance[family]["synthetic_comparator_gates"] = all(acceptance[family].values())
    summary = {"status": "SYNTHETIC_DEVELOPMENT_ONLY", "promotion": False, "protocol": protocol,
               "occupancy": occupancy, "label_distribution": dict(Counter(row["label"] for row in rows)),
               **frozen_selection, "development_audit": dev, "frozen_audit": frozen, "original_gates": gates,
               "acceptance": acceptance,
               "model_sha256": {family: _hash(artifacts / "candidates" / family / "model.joblib") for family in models},
               "training_sha256": _hash(artifacts / "training.csv")}
    _write(output / "research_summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--train-traces", type=int, default=144)
    parser.add_argument("--validation-traces", type=int, default=60)
    parser.add_argument("--development-audit-traces", type=int, default=120)
    parser.add_argument("--frozen-traces", type=int, default=1000)
    args = parser.parse_args()
    run(args.output, args.artifacts, args.train_traces, args.validation_traces,
        args.development_audit_traces, args.frozen_traces)


if __name__ == "__main__":
    main()
