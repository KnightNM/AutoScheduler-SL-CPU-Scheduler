"""Response-tail v5 research: frozen development protocol, no model promotion."""

import argparse
from collections import Counter
from dataclasses import replace
import json
from pathlib import Path
from statistics import mean
import subprocess
import sys

from autoscheduler.dataset import save_dataset
from autoscheduler.dynamic import DYNAMIC_FEATURE_NAMES, DynamicRouterConfig, _percentile, run_dynamic
from autoscheduler.dynamic_training import build_training_data, prepare_validation, validation_metrics
from autoscheduler.dynamic_v3_experiment import _write, _hash, tune_static, save_audit
from autoscheduler.evaluation import DEPLOYABLE_ALGORITHMS, score_result_against_reference
from autoscheduler.experiments import paired_bootstrap_ci
from autoscheduler.fairness import aggregate_fairness
from autoscheduler.model import train_model, load_model, select_eligible_family
from scheduler.mlfq import mlfq
from simulator.simulator import run_simulation


def ci(values):
    if min(values) == max(values):
        return {"mean": values[0], "ci_low": values[0], "ci_high": values[0]}
    return paired_bootstrap_ci(values)


def historical_v4(cases, archive: Path, model: Path, label="Dynamic v4"):
    """Same workload inputs, isolated original source and original model schema."""
    payload = [{"seed": w.seed, "family": w.family, "processes": [
        {key: getattr(p, key) for key in ("pid", "arrival_time", "burst_time", "priority", "cpu_bursts", "io_bursts")}
        for p in w.processes]} for w, _, _ in cases]
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
 jobs=[Process(**p) for p in item["processes"]]
 result=run_dynamic(jobs,model,config)
 latencies.extend(d.transition_ms for d in result.decisions)
 rows.append({"seed":item["seed"],"family":item["family"],"policy":sys.argv[3],
  "score":score_result_against_reference(result.simulation,compare_algorithms(jobs)),
  "p95_response":_percentile([m.response_time for m in result.simulation.process_metrics],.95),
  "worst_response":max(m.response_time for m in result.simulation.process_metrics),
  "starvation":aggregate_fairness(result.simulation.process_metrics)["starvation_count"],
  "switches":sum(d.accepted for d in result.decisions),"decision_p99_ms":result.transition_p99_ms,
  "guard_blocks":sum(d.reason=="first_service_protection" for d in result.decisions),"safety_returns":0,
  "dwell_blocks":sum(d.reason=="dwell_blocked" for d in result.decisions)})
json.dump({"rows":rows,"pooled_p99_ms":_percentile(latencies,.99)},sys.stdout)
'''
    replay = subprocess.run([sys.executable, "-c", code, str(archive.resolve()), str(model.resolve()), label],
                            input=json.dumps(payload), capture_output=True, text=True, check=True)
    return json.loads(replay.stdout)


def paired(records, baseline, metrics=("score", "p95_response", "worst_response", "starvation", "switches")):
    by_seed = {row["seed"]: row for row in baseline}
    if len(by_seed) != len(records) or set(by_seed) != {r["seed"] for r in records}:
        raise ValueError("paired audit requires identical unique workload seeds")
    return {key + "_difference": ci([r[key] - by_seed[r["seed"]][key] for r in records]) for key in metrics}


def acceptance(comparisons, max_latency):
    primary, rr = comparisons[0], comparisons[1]
    return {"primary_score": primary["score_difference"]["ci_high"] < 0,
            "primary_p95": primary["p95_response_difference"]["ci_high"] <= 0,
            "primary_starvation": primary["starvation_difference"]["mean"] <= 0,
            "latency": max_latency < 10,
            "original_rr_score": rr["score_difference"]["ci_high"] <= 0,
            "original_rr_p95": rr["p95_response_difference"]["ci_high"] < 0}


def audit(cases, models, config, tuned, primary, previous, previous_label="Dynamic v4"):
    records, latencies = [], {name: [] for name in models}
    for workload, static, references in cases:
        results = {name: static[name] for name in DEPLOYABLE_ALGORITHMS}
        results["Tuned MLFQ"] = run_simulation("Tuned MLFQ", mlfq, list(workload.processes), **tuned)
        routers = {}
        for name, model in models.items():
            router = run_dynamic(workload.processes, model, config)
            routers[name] = router
            results[name] = router.simulation
            latencies[name].extend(d.transition_ms for d in router.decisions)
        for name, result in results.items():
            decisions = routers[name].decisions if name in routers else []
            records.append({"seed": workload.seed, "family": workload.family, "policy": name,
                "score": score_result_against_reference(result, references),
                "p95_response": _percentile([m.response_time for m in result.process_metrics], .95),
                "worst_response": max(m.response_time for m in result.process_metrics),
                "starvation": aggregate_fairness(result.process_metrics)["starvation_count"],
                "switches": sum(d.accepted for d in decisions),
                "decision_p99_ms": routers[name].transition_p99_ms if name in routers else None,
                "guard_blocks": sum(d.reason in {"arrival_risk", "io_ready_pressure", "first_service_protection"} for d in decisions),
                "safety_returns": sum(d.accepted and d.reason in {"excursion_expired", "first_response_return"} for d in decisions),
                "dwell_blocks": sum(d.reason in {"dwell_blocked", "response_dwell_blocked"} for d in decisions)})
    records.extend(previous["rows"])
    grouped = {name: [r for r in records if r["policy"] == name] for name in dict.fromkeys(r["policy"] for r in records)}
    summary = {}
    for name, rows in grouped.items():
        data = {"mean_" + key: mean(r[key] for r in rows) for key in (
            "score", "p95_response", "worst_response", "starvation", "switches", "guard_blocks", "safety_returns", "dwell_blocks")}
        data["max_first_response"] = max(r["worst_response"] for r in rows)
        data["pooled_routing_p99_ms"] = (previous["pooled_p99_ms"] if name == previous_label else
                                         _percentile(latencies[name], .99) if name in models else None)
        measured = [r["decision_p99_ms"] for r in rows if r["decision_p99_ms"] is not None]
        data["max_workload_decision_p99_ms"] = max(measured) if measured else None
        data["by_family"] = {}
        for family in sorted({r["family"] for r in rows}):
            group = [r for r in rows if r["family"] == family]
            family_data = {"mean_" + key: mean(r[key] for r in group)
                           for key in ("score", "p95_response", "starvation", "switches", "worst_response")}
            family_data["max_first_response"] = max(r["worst_response"] for r in group)
            if name in models and name != "MLFQ control":
                family_data["comparisons"] = {baseline: paired(group,
                    [r for r in grouped[baseline] if r["family"] == family], ("score", "p95_response", "starvation"))
                    for baseline in dict.fromkeys((primary, previous_label))}
            data["by_family"][family] = family_data
        if name in models and name != "MLFQ control":
            data["comparisons"] = {baseline: paired(rows, grouped[baseline])
                                   for baseline in dict.fromkeys((primary, previous_label, "MLFQ", "Round Robin"))}
            data["gates"] = acceptance((data["comparisons"][primary], data["comparisons"]["Round Robin"]),
                                       data["max_workload_decision_p99_ms"])
        summary[name] = data
    return records, summary


def run(output: Path, artifacts: Path, *, quiet_dwell_periods=1,
        seeds=(9701, 9702, 9703), previous_version=4, experiment_version=5):
    if (output / "protocol.json").exists() or (artifacts / "split.json").exists():
        raise ValueError("use new versioned paths; never overwrite an experiment")
    archive = artifacts / "before_source"
    v4_model = Path(f"artifacts/dynamic_v{previous_version}_20261019/policy_cost/model.joblib")
    previous_label = f"Dynamic v{previous_version}"
    train_seed, validation_seed, audit_seed = seeds
    if not (archive / "autoscheduler/dynamic.py").exists() or not v4_model.exists():
        raise ValueError("preserved previous source and cost model are required before fitting")
    base = DynamicRouterConfig(epoch_ticks=10, dwell_epochs=2, confidence_threshold=.8,
        initial_policy="MLFQ", fallback_policy="MLFQ", explicit_no_switch=True, response_tail_protection=True,
        arrival_quiet_dwell_periods=quiet_dwell_periods)
    protocol = {"status": "SYNTHETIC_DEVELOPMENT_ONLY", "promotion": False, "python": sys.version,
        "seeds": {"train": train_seed, "validation": validation_seed, "audit": audit_seed},
        "experiment_version": experiment_version,
        "single_correction": "observed quiet admission window in dwell periods; no threshold search",
        "traces": {"train": 144, "validation": 84, "audit": 240}, "config_before_static_tuning": base.__dict__,
        "workloads": "unchanged_v4_six_family_generator; new seeds; no outcome filtering",
        "selection": "eligible_families_only_then_realized_score; None means retain static comparator",
        "classifier_grid": [[d, 10, w] for d in (3, 5, 8) for w in (None, "balanced")],
        "cost_grid": [[d, 10, None] for d in (3, 5, 8)], "refit": False,
        "static_grid": {"quanta": [[1, 2, 4], [2, 4, 8], [4, 8, 16]], "aging": [10, 20, 40]},
        "gate_definitions": "primary score CI_high<0; P95 CI_high<=0; mean starvation<=baseline; max workload routing P99<10ms; original RR gates unchanged",
        "confidence_intervals": "paired workload percentile bootstrap; 10000 resamples; seed2027; family CIs exploratory",
        "old_1000_and_locked_real_tests": "NOT_USED",
        "previous_model_sha256": _hash(v4_model), "previous_source_sha256": _hash(archive / "autoscheduler/dynamic.py"),
        "source_sha256": {str(p): _hash(p) for p in [Path(name) for name in (
            "autoscheduler/dynamic.py", "autoscheduler/model.py", "autoscheduler/dynamic_training.py",
            "autoscheduler/development_workloads.py", "autoscheduler/dynamic_v5_experiment.py",
            "autoscheduler/evaluation.py", "simulator/engine.py", "configs/real_desktop_ml.json")]}}
    _write(output / "protocol.json", protocol)
    print("Freezing development-selected static comparator", flush=True)
    cases, static_validation = prepare_validation(84, validation_seed, base, development="v4")
    tuned, grid = tune_static(cases)
    config = replace(base, mlfq_quanta=tuple(tuned["quanta"]), mlfq_aging_threshold=tuned["aging_threshold"])
    static_scores = {**static_validation["static_scores"], "Tuned MLFQ": min(c["validation_score"] for c in grid)}
    primary = min(static_scores, key=static_scores.get)
    baselines = [run_simulation("Tuned MLFQ", mlfq, list(w.processes), **tuned) for w, _, _ in cases]
    if primary != "Tuned MLFQ":
        baselines = [static[primary] for _, static, _ in cases]
    _write(output / "static_selection.json", {"primary": primary, "validation_scores": static_scores,
        "tuned_parameters": tuned, "grid": grid, "config": config.__dict__})
    print("Building grouped training labels and train-only pilot occupancy", flush=True)
    rows, occupancy = build_training_data(144, train_seed, config, artifacts / "split.json", development="v4")
    save_dataset(rows, artifacts / "training.csv")
    models, validation = {}, {}
    for family in ("classifier", "policy_cost"):
        print(f"Comparing constrained {family} trees", flush=True)
        path = artifacts / family / "model.joblib"
        settings = [(d, 10, w) for d in (3, 5, 8) for w in ((None, "balanced") if family == "classifier" else (None,))]
        report = train_model(rows, path, train_seed, feature_names=DYNAMIC_FEATURE_NAMES,
            metadata={"dynamic_config": config.__dict__, "static_baseline": static_validation["static_baseline"],
                      "primary_baseline": primary, "response_tail_protocol": "observed_quiet_gate_and_minimum_dwell_excursion"},
            model_kind=family, candidate_settings=settings, refit=False,
            scheduler_validation=lambda model: validation_metrics(model, cases, config, baseline_results=baselines))
        models[family] = load_model(path, DYNAMIC_FEATURE_NAMES, expected_dynamic_config=config)
        validation[family] = {k: v for k, v in report.items() if k.startswith("validation_schedule_")}
        _write(output / f"{family}_training.json", report)
    selected = select_eligible_family(validation)
    _write(output / "frozen_selection.json", {"selected": selected, "fallback": primary,
        "diagnostic_models": [name for name in models if not validation[name]["validation_schedule_eligible"]],
        "validation": validation})
    print(f"Development selection: {selected}; one fresh audit (no post-audit retuning)", flush=True)
    cases, _ = prepare_validation(240, audit_seed, config, development="v4")
    previous = historical_v4(cases, archive, v4_model, previous_label)
    _write(output / f"v{previous_version}_replay.json", previous)
    records, summary = audit(cases, {**models, "MLFQ control": None}, config, tuned, primary, previous, previous_label)
    save_audit(output / "audit", records, summary)
    accepted = {name: bool(validation[name]["validation_schedule_eligible"] and all(summary[name]["gates"].values())) for name in models}
    selected_final = selected if selected is not None and accepted[selected] else None
    result = {"status": "SYNTHETIC_DEVELOPMENT_ONLY", "promotion": False, "protocol": protocol,
        "config": config.__dict__, "occupancy": occupancy, "label_distribution": dict(Counter(r["label"] for r in rows)),
        "primary_baseline": primary, "tuned_parameters": tuned, "development_selected": selected,
        "accepted_after_audit": selected_final, "acceptance": accepted,
        "recommendation": primary if selected_final is None else "requires_locked_real_trace_validation",
        "validation": validation, "audit": summary,
        "model_sha256": {name: _hash(artifacts / name / "model.joblib") for name in models}}
    _write(output / "research_summary.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    args = parser.parse_args()
    run(args.output, args.artifacts)


if __name__ == "__main__":
    main()
