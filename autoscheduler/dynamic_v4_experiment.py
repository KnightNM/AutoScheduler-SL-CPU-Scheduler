"""One small safety-constrained synthetic development experiment; never promotes."""

import argparse
from collections import Counter
from dataclasses import replace
import json
from pathlib import Path
from statistics import mean
import subprocess
import sys

from autoscheduler.dataset import save_dataset
from autoscheduler.dynamic import DYNAMIC_FEATURE_NAMES, DynamicRouterConfig, _percentile
from autoscheduler.dynamic_training import build_training_data, prepare_validation, validation_metrics
from autoscheduler.dynamic_v3_experiment import _write, _hash, tune_static, audit_cases, save_audit
from autoscheduler.experiments import paired_bootstrap_ci
from autoscheduler.model import train_model, load_model, scheduling_candidate_key
from scheduler.mlfq import mlfq
from simulator.simulator import run_simulation


def previous_v3(cases, archive: Path, model: Path):
    """Isolated original implementation; never relax the active schema loader."""
    payload = [{"seed": workload.seed, "family": workload.family, "processes": [
        {key: getattr(process, key) for key in ("pid", "arrival_time", "burst_time", "priority", "cpu_bursts", "io_bursts")}
        for process in workload.processes]} for workload, _, _ in cases]
    code = '''
import sys,json
sys.path.insert(0,sys.argv[1])
from autoscheduler.dynamic import DYNAMIC_FEATURE_NAMES,DynamicRouterConfig,run_dynamic,_percentile
from autoscheduler.model import load_model,load_model_metadata
from autoscheduler.evaluation import compare_algorithms,score_result_against_reference
from autoscheduler.fairness import aggregate_fairness
from simulator.process import Process
model=load_model(sys.argv[2],DYNAMIC_FEATURE_NAMES)
config=DynamicRouterConfig(**load_model_metadata(sys.argv[2])["dynamic_config"])
rows=[];latencies=[]
for item in json.load(sys.stdin):
 processes=[Process(**p) for p in item["processes"]]
 result=run_dynamic(processes,model,config)
 latencies.extend(d.transition_ms for d in result.decisions)
 rows.append({"seed":item["seed"],"family":item["family"],"policy":"Dynamic v3",
  "score":score_result_against_reference(result.simulation,compare_algorithms(processes)),
  "p95_response":_percentile([m.response_time for m in result.simulation.process_metrics],.95),
  "starvation":aggregate_fairness(result.simulation.process_metrics)["starvation_count"],
  "switches":sum(d.accepted for d in result.decisions),"decision_p99_ms":result.transition_p99_ms})
json.dump({"rows":rows,"pooled_p99_ms":_percentile(latencies,.99)},sys.stdout)
'''
    result = subprocess.run([sys.executable, "-c", code, str(archive.resolve()), str(model.resolve())],
                            input=json.dumps(payload), text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


def paired(rows, baseline_rows):
    baseline = {row["seed"]: row for row in baseline_rows}
    assert set(baseline) == {row["seed"] for row in rows}
    return {key: paired_bootstrap_ci([row[key] - baseline[row["seed"]][key] for row in rows])
            for key in ("score", "p95_response", "starvation", "switches")}


def run(output: Path, artifacts: Path, train_traces=72, validation_traces=36, audit_traces=120):
    if (output / "protocol.json").exists() or (artifacts / "split.json").exists():
        raise ValueError("use fresh versioned output paths")
    if train_traces < 36 or train_traces % 36 or validation_traces % 6 or audit_traces % 6:
        raise ValueError("use complete family/behavior blocks and balanced evaluation families")
    if not (artifacts / "before_source/autoscheduler/dynamic.py").exists():
        raise ValueError("copy the archived v3 before_source into the new artifact directory before fitting")
    base = DynamicRouterConfig(epoch_ticks=10, dwell_epochs=2, confidence_threshold=.8,
                               initial_policy="MLFQ", fallback_policy="MLFQ", explicit_no_switch=True)
    protocol = {"status": "SYNTHETIC_DEVELOPMENT_ONLY", "promotion": False,
        "seeds": {"train": 8401, "validation": 8402, "audit": 8403},
        "traces": {"train": train_traces, "validation": validation_traces, "audit": audit_traces},
        "workload_suite": "v4_balanced_six_families_no_outcome_filtering",
        "counts": [3, 6, 12, 24, 48], "base_config": base.__dict__,
        "python": sys.version,
        "classifier_grid": [[depth, 10, weight] for depth in (3, 5, 8) for weight in (None, "balanced")],
        "cost_grid": [[depth, 10, None] for depth in (3, 5, 8)],
        "refit": False, "selection": "safety_eligible_first_then_realized_score; no audit retuning",
        "static_grid": {"quanta": [[1, 2, 4], [2, 4, 8], [4, 8, 16]], "aging": [10, 20, 40]},
        "gates": "primary score CI_high<0; primary P95 CI_high<=0; mean starvation<=baseline; max workload routing P99<10ms; original RR gates unchanged",
        "old_1000_workload_audit": "NOT_RUN; historical numbers are context only",
        "source_sha256": {str(path): _hash(path) for path in [Path(p) for p in (
            "autoscheduler/dynamic.py", "autoscheduler/model.py", "autoscheduler/dynamic_training.py",
            "autoscheduler/development_workloads.py", "autoscheduler/dynamic_v4_experiment.py",
            "autoscheduler/dynamic_v3_experiment.py", "autoscheduler/evaluation.py", "simulator/engine.py",
            "configs/real_desktop_ml.json")]}}
    _write(output / "protocol.json", protocol)
    print("Freezing development static comparator before fitting", flush=True)
    cases, static_validation = prepare_validation(validation_traces, 8402, base, development="v4")
    tuned, grid = tune_static(cases)
    config = replace(base, mlfq_quanta=tuple(tuned["quanta"]), mlfq_aging_threshold=tuned["aging_threshold"])
    tuned_results = [run_simulation("Tuned MLFQ", mlfq, list(w.processes), **tuned) for w, _, _ in cases]
    scores = {**static_validation["static_scores"], "Tuned MLFQ": min(c["validation_score"] for c in grid)}
    comparator = min(scores, key=scores.get)
    baseline_results = tuned_results if comparator == "Tuned MLFQ" else [static[comparator] for _, static, _ in cases]
    _write(output / "static_selection.json", {"config": config.__dict__, "primary_baseline": comparator,
        "validation_scores": scores, "grid": grid, "tuned_parameters": tuned})
    print("Building grouped feasible-action labels and train-only pilot states", flush=True)
    rows, occupancy = build_training_data(train_traces, 8401, config, artifacts / "split.json", development="v4")
    save_dataset(rows, artifacts / "training.csv")
    models, reports, validation = {}, {}, {}
    for family in ("classifier", "policy_cost"):
        print(f"Selecting {family} from small safety-first grid", flush=True)
        path = artifacts / family / "model.joblib"
        settings = [(depth, 10, weight) for depth in (3, 5, 8)
                    for weight in ((None, "balanced") if family == "classifier" else (None,))]
        reports[family] = train_model(rows, path, 8401, feature_names=DYNAMIC_FEATURE_NAMES,
            metadata={"dynamic_config": config.__dict__, "static_baseline": static_validation["static_baseline"],
                      "primary_baseline": comparator, "target": "negative_cost_is_benefit_vs_MLFQ; explicit_No_Switch_holds_current_policy"},
            model_kind=family, candidate_settings=settings, refit=False,
            scheduler_validation=lambda candidate: validation_metrics(candidate, cases, config, baseline_results=baseline_results))
        models[family] = load_model(path, DYNAMIC_FEATURE_NAMES, expected_dynamic_config=config)
        # The report contains the selected model's original measurement; no
        # repeated validation timing is used to replace a failed measurement.
        validation[family] = {key: value for key, value in reports[family].items() if key.startswith("validation_schedule_")}
        _write(output / f"{family}_training.json", reports[family])
    selected = min(validation, key=lambda name: (*scheduling_candidate_key(validation[name]), name))
    selection = {"selected": selected, "validation": validation, "primary_baseline": comparator, "config": config.__dict__}
    _write(output / "frozen_selection.json", selection)
    print(f"Frozen candidate {selected}; one fresh development audit (no frozen-1000 replay)", flush=True)
    audit, _ = prepare_validation(audit_traces, 8403, config, development="v4")
    records, summary = audit_cases(audit, {**models, "Protected MLFQ control": None}, config, tuned)
    save_audit(output / "audit", records, summary)
    previous = previous_v3(audit, artifacts / "before_source",
                            Path("artifacts/dynamic_v3_20261019/candidates/classifier/model.joblib"))
    _write(output / "previous_v3.json", previous)
    before_rows = previous["rows"]
    before_summary = {"mean_" + key: mean(row[key] for row in before_rows)
                      for key in ("score", "p95_response", "starvation", "switches")}
    before_summary.update(decision_p99_ms=previous["pooled_p99_ms"],
                          max_workload_decision_p99_ms=max(row["decision_p99_ms"] for row in before_rows))
    acceptance, changes = {}, {}
    for family in models:
        result = summary[family]
        primary = result["comparisons"][comparator]
        rr = result["comparisons"]["Round Robin"]
        gates = {"primary_score": primary["score_difference"]["ci_high"] < 0,
                 "primary_response": primary["p95_response_difference"]["ci_high"] <= 0,
                 "primary_starvation": primary["starvation_difference"]["mean"] <= 0,
                 "latency": result["max_workload_decision_p99_ms"] < 10,
                 "original_rr_score": rr["score_difference"]["ci_high"] <= 0,
                 "original_rr_p95": rr["p95_response_difference"]["ci_high"] < 0}
        acceptance[family] = {"audit_gates": gates, "audit_eligible": all(gates.values()),
                             "development_validation_eligible": validation[family]["validation_schedule_eligible"],
                             "accepted": all(gates.values()) and validation[family]["validation_schedule_eligible"]}
        changes[family] = paired([row for row in records if row["policy"] == family], before_rows)
    result = {"status": "SYNTHETIC_DEVELOPMENT_ONLY", "promotion": False, "protocol": protocol,
              **selection, "tuned_parameters": tuned, "occupancy": occupancy,
              "label_distribution": dict(Counter(row["label"] for row in rows)), "audit": summary,
              "before_v3_same_audit": before_summary, "changes_vs_v3": changes, "acceptance": acceptance,
              "recommendation": "Tuned MLFQ" if not acceptance[selected]["accepted"] else "candidate_requires_locked_real_trace_validation",
              "model_sha256": {family: _hash(artifacts / family / "model.joblib") for family in models}}
    _write(output / "research_summary.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--artifacts", required=True, type=Path)
    args = parser.parse_args()
    run(args.output, args.artifacts)


if __name__ == "__main__":
    main()
