"""Reproducible synthetic audit; never selects a final real-desktop model."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
from statistics import mean
import subprocess

from autoscheduler.dataset import save_dataset
from autoscheduler.dynamic import (
    DYNAMIC_FEATURE_NAMES, DynamicRouterConfig, evaluate_dynamic, save_dynamic_evaluation,
)
from autoscheduler.dynamic_training import build_training_data, prepare_validation, validation_metrics
from autoscheduler.model import load_model, train_model


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _before_summary(path: Path, comparator: str) -> dict:
    """Use an explicitly captured legacy replay, never load it for inference."""
    from autoscheduler.dynamic import DYNAMIC_POLICY_NAMES, _percentile
    from autoscheduler.experiments import paired_bootstrap_ci

    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data["rows"]
    return {
        "source_model": data["source_model"], "sha256": data["sha256"],
        "traces": data["traces"], "seed": data["seed"], "config": data["config"],
        "normalization": "frozen_six_static_policy_bounds",
        "mean_weighted_score": mean(row["adaptive"]["score_frozen_six"] for row in rows),
        "mean_p95_response": mean(row["adaptive"]["p95_response"] for row in rows),
        "mean_starvation_count": mean(row["adaptive"]["starvation_count"] for row in rows),
        "mean_accepted_switches": mean(row["switches"] for row in rows),
        "mean_scheduling_regret": mean(
            row["adaptive"]["score_frozen_six"] - min(row["static"][p]["score_frozen_six"] for p in DYNAMIC_POLICY_NAMES)
            for row in rows
        ),
        "decision_p99_ms": _percentile([value for row in rows for value in row["latencies_ms"]], .99),
        "baseline_score_difference": paired_bootstrap_ci([
            row["adaptive"]["score_frozen_six"] - row["static"][comparator]["score_frozen_six"] for row in rows
        ]),
        "historical_oracle_actions_and_hidden_features": True,
    }


def run_research(
    output: Path, artifacts: Path, before: Path | None = None,
    train_traces: int = 120, validation_traces: int = 60, evaluation_traces: int = 1000,
) -> dict:
    """Freeze protocol, fit on development, choose on validation, then audit test."""
    import sklearn

    if (output / "protocol.json").exists() or (artifacts / "split.json").exists():
        raise ValueError("research output already exists; use a new versioned path")
    if train_traces < 4 or validation_traces <= 0 or evaluation_traces <= 0:
        raise ValueError("research needs at least four training traces and positive evaluation sizes")
    config = DynamicRouterConfig(epoch_ticks=10, dwell_epochs=2, confidence_threshold=.8)
    output.mkdir(parents=True, exist_ok=True)
    artifacts.mkdir(parents=True, exist_ok=True)
    protocol = {
        "status": "SYNTHETIC_DEVELOPMENT_ONLY", "config": config.__dict__,
        "train": {"traces": train_traces, "seed": 42},
        "validation": {"traces": validation_traces, "seed": 4242},
        "evaluation": {"traces": evaluation_traces, "seed": 2026},
        "family_selection": "lowest_realized_whole_workload_validation_score_before_evaluation",
        "hyperparameter_selection": "realized_validation_schedule_score_then_action_regret_then_simpler_tree",
        "cost_switch_margin": .005,
        "python": platform.python_version(), "sklearn": sklearn.__version__,
        "base_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "source_sha256": {str(path): _sha256(path) for path in (
            Path("autoscheduler/dynamic.py"), Path("autoscheduler/model.py"),
            Path("autoscheduler/dynamic_training.py"), Path("autoscheduler/evaluation.py"),
            Path("autoscheduler/workloads.py"), Path("simulator/engine.py"),
            Path("configs/real_desktop_ml.json"), Path(__file__).relative_to(Path.cwd()),
        )},
    }
    (output / "protocol.json").write_text(json.dumps(protocol, indent=2), encoding="utf-8")
    print("Building grouped development data and train-only pilot rollouts", flush=True)
    rows, occupancy = build_training_data(train_traces, 42, config, artifacts / "split.json")
    save_dataset(rows, artifacts / "training.csv")
    cases, validation = prepare_validation(validation_traces, 4242, config)
    comparator = validation["static_baseline"]
    print(f"Frozen static comparator: {comparator}", flush=True)
    reports, models, validation_scores = {}, {}, {}
    for family in ("classifier", "policy_cost"):
        path = artifacts / family / "model.joblib"
        print(f"Fitting {family} by realized development scheduling score", flush=True)
        reports[family] = train_model(
            rows, path, 42, feature_names=DYNAMIC_FEATURE_NAMES,
            metadata={"dynamic_config": config.__dict__, "static_baseline": comparator},
            model_kind=family, scheduler_validation=lambda model: validation_metrics(model, cases, config),
        )
        models[family] = load_model(path, DYNAMIC_FEATURE_NAMES, expected_dynamic_config=config)
        validation_scores[family] = validation_metrics(models[family], cases, config)
        (output / f"{family}_training.json").write_text(json.dumps(reports[family], indent=2), encoding="utf-8")
    selected = min(validation_scores, key=lambda family: (validation_scores[family]["validation_schedule_score"], family))
    frozen_selection = {"selected": selected, "static_baseline": comparator, "validation": validation,
                        "family_validation": validation_scores}
    (output / "frozen_selection.json").write_text(json.dumps(frozen_selection, indent=2), encoding="utf-8")
    print(f"Frozen candidate: {selected}. Auditing untouched seed-2026 workloads", flush=True)
    evaluations = {}
    for family, model in models.items():
        evaluation_rows, evaluations[family] = evaluate_dynamic(
            model, evaluation_traces, 2026, config, frozen_static_baseline=comparator,
        )
        save_dynamic_evaluation(evaluation_rows, evaluations[family], output / family)
    summary = {
        "status": "SYNTHETIC_DEVELOPMENT_ONLY", "protocol": protocol,
        "occupancy": occupancy, **frozen_selection, "evaluations": evaluations,
        "model_sha256": {family: _sha256(artifacts / family / "model.joblib") for family in models},
        "training_data_sha256": _sha256(artifacts / "training.csv"),
        "beats_strongest_eligible_static_baseline": evaluations[selected]["beats_frozen_static_baseline"],
        "real_desktop_eligibility": "NOT_ESTABLISHED_NO_LOCKED_REAL_TRACE_VALIDATION",
    }
    if before is not None:
        legacy = _before_summary(before, comparator)
        if (legacy["traces"], legacy["seed"]) != (evaluation_traces, 2026):
            raise ValueError("before replay must use the same untouched evaluation workloads")
        summary["before"] = legacy
        summary["before_capture_sha256"] = _sha256(before)
    (output / "research_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--before", type=Path)
    parser.add_argument("--train-traces", type=int, default=120)
    parser.add_argument("--validation-traces", type=int, default=60)
    parser.add_argument("--evaluation-traces", type=int, default=1000)
    args = parser.parse_args()
    summary = run_research(args.output, args.artifacts, args.before, args.train_traces,
                           args.validation_traces, args.evaluation_traces)
    print(f"Beats frozen static comparator: {summary['beats_strongest_eligible_static_baseline']}")


if __name__ == "__main__":
    main()
