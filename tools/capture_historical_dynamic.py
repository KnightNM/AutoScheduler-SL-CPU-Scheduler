"""Explicit historical replay only; hidden-feature models never enter inference.

Run from the repo root: .venv/bin/python tools/capture_historical_dynamic.py
--revision <original-commit> --model results/six_policy/dynamic_model.joblib
--output artifacts/dynamic_v2_comparison/before.json
"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import types

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autoscheduler.evaluation import compare_algorithms, score_result_against_reference, SCORE_WEIGHTS
from autoscheduler.fairness import aggregate_fairness
from scheduler.mlfq import mlfq
from simulator.simulator import run_simulation


def main():
    import joblib

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--traces", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()
    if args.output.exists() or args.traces <= 0:
        raise ValueError("use a new output path and a positive trace count")
    revision = subprocess.check_output(["git", "rev-parse", "--verify", args.revision], text=True).strip()
    source = subprocess.check_output(["git", "show", f"{revision}:autoscheduler/dynamic.py"], text=True)
    legacy = types.ModuleType("_historical_dynamic")
    sys.modules[legacy.__name__] = legacy
    # This executes a user-selected local revision, just as a historical checkout
    # would. The active router and its saved-model loader are never relaxed.
    exec(compile(source, f"{revision}:autoscheduler/dynamic.py", "exec"), legacy.__dict__)
    bundle = joblib.load(args.model)
    if tuple(bundle["features"]) != legacy.DYNAMIC_FEATURE_NAMES:
        raise ValueError("historical model features must match the selected revision")
    config = legacy.DynamicRouterConfig(**bundle["metadata"]["dynamic_config"])
    rr_config = bundle["metadata"]["priority_rr_config"]
    rows = []
    for index in range(args.traces):
        workload = legacy.generate_dynamic_workload(args.seed * 1_000_000 + index)
        adaptive = legacy.run_dynamic(workload.processes, bundle["model"], config, rr_config)
        references = compare_algorithms(workload.processes, rr_config)
        results = {**references, "MLFQ": run_simulation("MLFQ", mlfq, list(workload.processes),
                                                       quanta=(2, 4, 8), aging_threshold=20)}

        def metrics(result):
            return {
                "score_frozen_six": score_result_against_reference(result, references),
                "p95_response": legacy._percentile([metric.response_time for metric in result.process_metrics], .95),
                "starvation_count": aggregate_fairness(result.process_metrics)["starvation_count"],
                **{key: getattr(result, key) for key in SCORE_WEIGHTS},
            }

        rows.append({
            "seed": workload.seed, "adaptive": metrics(adaptive.simulation),
            "static": {policy: metrics(result) for policy, result in results.items()},
            "switches": sum(decision.accepted for decision in adaptive.decisions),
            "latencies_ms": [decision.transition_ms for decision in adaptive.decisions],
        })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({
        "source_model": str(args.model), "source_revision": revision,
        "sha256": hashlib.sha256(args.model.read_bytes()).hexdigest(), "config": config.__dict__,
        "traces": args.traces, "seed": args.seed, "rows": rows,
    }), encoding="utf-8")
    print(f"Historical replay saved: {args.output}")


if __name__ == "__main__":
    main()
