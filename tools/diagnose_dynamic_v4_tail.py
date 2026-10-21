"""Retrospective v4 tail diagnosis using archived source, never controller inputs."""

import csv
import json
from pathlib import Path
from statistics import mean
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "artifacts/dynamic_v5_20261019/before_source"))

from autoscheduler.development_workloads import generate_development_workload_v4
from autoscheduler.dynamic import DYNAMIC_FEATURE_NAMES, DynamicRouterConfig, _percentile, run_dynamic
from autoscheduler.model import load_model, load_model_metadata
from scheduler.mlfq import mlfq
from simulator.simulator import run_simulation


def trace(workload, dynamic, static):
    starts = {m.pid: m.response_time + next(p.arrival_time for p in workload.processes if p.pid == m.pid)
              for m in dynamic.simulation.process_metrics}
    baseline = {m.pid: m.response_time for m in static.process_metrics}
    cutoff = _percentile(list(baseline.values()), .95)
    processes = []
    for job in workload.processes:
        first = starts[job.pid]
        arrivals_active = dynamic.initial_policy
        for decision in dynamic.decisions:
            if decision.time <= job.arrival_time:
                arrivals_active = decision.active
        reviews = [d for d in dynamic.decisions if job.arrival_time <= d.time < first]
        occupied = [(pid, a, b) for pid, a, b in dynamic.simulation.timeline
                    if a <= job.arrival_time < b and pid != job.pid]
        response = first - job.arrival_time
        processes.append({"pid": job.pid, "arrival": job.arrival_time, "first_dispatch": first,
            "response": response, "mlfq_first_dispatch": job.arrival_time + baseline[job.pid],
            "mlfq_response": baseline[job.pid], "exceeds_mlfq_workload_p95": response > cutoff,
            "in_dynamic_top_tail": response >= _percentile([m.response_time for m in dynamic.simulation.process_metrics], .95),
            "policy_at_arrival": arrivals_active,
            "initial_dispatch_residual": max((b - job.arrival_time for _, _, b in occupied), default=0),
            "dwell_blocked_reviews": sum(d.features["dwell_remaining_ticks"] > 0 and d.active != "MLFQ" for d in reviews),
            "legal_reviews_retaining_other_policy": sum(d.features["dwell_remaining_ticks"] == 0 and d.active != "MLFQ" for d in reviews),
            "cs_time_before_first": sum(max(0, min(b, first) - max(a, job.arrival_time))
                                         for pid, a, b in dynamic.simulation.timeline if pid == "CS")})
    decisions = []
    for d in dynamic.decisions:
        if d.accepted or d.features["first_service_ready_count"] > 0 or d.reason == "first_service_protection":
            decisions.append({"time": d.time, "selected": d.selected, "active": d.active,
                "accepted": d.accepted, "reason": d.reason, "features": d.features,
                "unserved_ready_waits": {job.pid: d.time - job.arrival_time for job in workload.processes
                                          if job.arrival_time <= d.time <= starts[job.pid]}})
    return {"mlfq_p95_cutoff": cutoff, "processes": processes, "decisions": decisions}


def main():
    output = ROOT / "results/dynamic_v5_20261019/diagnosis"
    output.mkdir(parents=True, exist_ok=True)
    source = ROOT / "results/dynamic_v4_20261019/audit/workloads.csv"
    frozen = list(csv.DictReader(source.open()))
    table = {(r["seed"], r["policy"]): r for r in frozen}
    records, representatives, mechanisms = [], {}, {}
    for family in ("classifier", "policy_cost"):
        path = ROOT / f"artifacts/dynamic_v4_20261019/{family}/model.joblib"
        model = load_model(path, DYNAMIC_FEATURE_NAMES)
        config = DynamicRouterConfig(**load_model_metadata(path)["dynamic_config"])
        counts = dict(regressed_processes=0, arrived_under_mlfq=0, arrived_under_other=0,
                      legal_return_missed=0, dwell_delayed=0, initial_dispatch_delayed=0, switch_overhead_delayed=0)
        for saved in (r for r in frozen if r["policy"] == family):
            workload = generate_development_workload_v4(int(saved["seed"]), saved["family"])
            dynamic = run_dynamic(workload.processes, model, config)
            static = run_simulation("Tuned MLFQ", mlfq, workload.processes,
                                     quanta=config.mlfq_quanta, aging_threshold=config.mlfq_aging_threshold)
            p95 = _percentile([m.response_time for m in dynamic.simulation.process_metrics], .95)
            assert abs(p95 - float(saved["p95_response"])) < 1e-9
            detailed = trace(workload, dynamic, static)
            delta = p95 - detailed["mlfq_p95_cutoff"]
            records.append({"seed": workload.seed, "family": workload.family, "model": family,
                            "p95": p95, "mlfq_p95": detailed["mlfq_p95_cutoff"], "difference": delta,
                            "worst_response": max(p["response"] for p in detailed["processes"])})
            key = family + "/" + workload.family
            if delta > 0 and (key not in representatives or delta > representatives[key]["p95_difference"]):
                representatives[key] = {"seed": workload.seed, "family": workload.family, "model": family,
                                       "p95_difference": delta, **detailed}
            for p in detailed["processes"]:
                if p["response"] > p["mlfq_response"]:
                    counts["regressed_processes"] += 1
                    counts["arrived_under_mlfq" if p["policy_at_arrival"] == "MLFQ" else "arrived_under_other"] += 1
                    counts["legal_return_missed"] += p["legal_reviews_retaining_other_policy"] > 0
                    counts["dwell_delayed"] += p["dwell_blocked_reviews"] > 0
                    counts["initial_dispatch_delayed"] += p["initial_dispatch_residual"] > 0
                    counts["switch_overhead_delayed"] += p["cs_time_before_first"] > 0
        mechanisms[family] = counts
    summary = {"status": "RETROSPECTIVE_DIAGNOSIS_NOT_SELECTION", "workloads_reproduced": len(records),
               "mechanism_counts_overlap": mechanisms, "families": {}}
    for model in ("classifier", "policy_cost"):
        summary["families"][model] = {family: {"mean_p95_difference": mean(r["difference"] for r in group),
             "positive_excess_sum": sum(max(0, r["difference"]) for r in group),
             "regressed_workloads": sum(r["difference"] > 1e-9 for r in group)}
             for family in sorted({r["family"] for r in records})
             for group in ([r for r in records if r["model"] == model and r["family"] == family],)}
    (output / "summary.json").write_text(json.dumps(summary, indent=2))
    (output / "representatives.json").write_text(json.dumps(representatives, indent=2))
    with (output / "workloads.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=records[0]); writer.writeheader(); writer.writerows(records)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
