"""Bounded, read-only demo adapter around the existing simulator.

Replay frames derive CPU service and I/O intervals from returned timeline slices
and the tiny declared workloads. Ready membership is exposed, not internal queue
order. No scheduling decisions are made here or in the browser.
"""
from dataclasses import asdict
from functools import lru_cache
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode

from autoscheduler.evaluation import ALGORITHMS, DEPLOYABLE_ALGORITHMS, SCORE_WEIGHTS, compare_algorithms, score_result_against_reference
from autoscheduler.features import extract_features
from autoscheduler.fairness import aggregate_fairness
from scheduler.mlfq import mlfq
from simulator.process import Process
from simulator.simulator import run_simulation

ROOT = Path(__file__).resolve().parents[1]
DYNAMIC_V5_NAME = 'Dynamic ML (v5)'
DYNAMIC_V5_ARTIFACT = 'artifacts/dynamic_v5_20261019/policy_cost/model.joblib'
MULTI_DEMO_ARTIFACT = 'artifacts/dynamic_multi_policy_demo_20261020/model.joblib'
MULTI_DEMO_LABEL = 'Experimental multi-policy demonstration model — not original fitted v5'
WORKLOADS = {
    "short_jobs": {"name": "Short-job-heavy", "description": "A long job meets a stream of short tasks. Compare responsiveness and completion order.",
                   "jobs": [(0, (12,), (), 3), (1, (2,), (), 1), (2, (1,), (), 2), (3, (3,), (), 1), (4, (2,), (), 2), (5, (1,), (), 1)]},
    "mixed_io": {"name": "Mixed CPU / I/O", "description": "Interactive tasks leave the CPU for I/O and return while CPU-bound jobs compete.",
                 "jobs": [(0, (2, 3, 2), (4, 3), 1), (0, (14,), (), 3), (1, (1, 2, 1), (5, 4), 2), (2, (7,), (), 2), (4, (2, 3), (3,), 1), (6, (3,), (), 3)]},
    "bursty": {"name": "Bursty arrivals", "description": "Two arrival bursts create changing queue pressure. Watch preemption and first service.",
               "jobs": [(0, (10,), (), 3), (0, (6,), (), 2), (1, (3,), (), 1), (8, (2,), (), 1), (8, (5,), (), 2), (9, (1,), (), 1), (14, (4,), (), 2), (14, (2,), (), 3)]},
    "dynamic_multi_policy": {"name": "Dynamic ML — Multi-Policy Switching Demo",
        "description": "Experimental multi-policy demonstration model — not original fitted v5. Same v5 safeguards; genuine fitted-cost decisions, not validated scheduling superiority.",
        "jobs": [(0, (30,), (), 0)] * 6 + [(33, (2,), (), 0)]},
}


def read_json(path):
    return json.loads((ROOT / path).read_text())


def processes(workload):
    if workload not in WORKLOADS:
        raise ValueError("Choose an available built-in demo workload.")
    return [Process(f"P{i}", arrival, sum(cpu), priority, cpu_bursts=cpu, io_bursts=io)
            for i, (arrival, cpu, io, priority) in enumerate(WORKLOADS[workload]["jobs"], 1)]


def catalog():
    metadata_path = "artifacts/demo_tree.json"
    metadata = read_json(metadata_path) if (ROOT / metadata_path).exists() else None
    return {"workloads": [{"id": key, "name": value["name"], "description": value["description"], "count": len(value["jobs"])}
                          for key, value in WORKLOADS.items()],
        "algorithms": list(ALGORITHMS) + ["MLFQ", "Tuned MLFQ", DYNAMIC_V5_NAME], "score_weights": SCORE_WEIGHTS,
        "offline": {"source": metadata_path, "metadata": metadata, "inference_available": False,
            "message": "Verified saved metadata is available. The matching fitted six-policy binary is not available; live predictions are not fabricated."},
        "research": read_json("configs/research_status.json"),
        "azure_adapted": read_json("results/azure_adapted_20261020/dashboard.json")
            if (ROOT / "results/azure_adapted_20261020/dashboard.json").exists() else None,
        "real_source_dynamic": read_json("results/real_source_dynamic_review_20261020/dashboard.json")
            if (ROOT / "results/real_source_dynamic_review_20261020/dashboard.json").exists() else None,
        "dynamic_v5_evaluation": read_json("results/dynamic_v5_review/analysis.json")
            if (ROOT / "results/dynamic_v5_review/analysis.json").exists() else None,
        "azure_external": {"source": "results/azure_external_pilot/summary.json",
            "summary": read_json("results/azure_external_pilot/summary.json")}
            if (ROOT / "results/azure_external_pilot/summary.json").exists() else None,
        "bakeoff": {"source": "results/real_desktop_ml/decision-tree-demo/summary.json",
                    "summary": read_json("results/real_desktop_ml/decision-tree-demo/summary.json")}}


def _run(jobs, algorithm):
    if algorithm == DYNAMIC_V5_NAME:
        return _run_v5(jobs).simulation
    if algorithm == "Tuned MLFQ":
        parameters = read_json("configs/research_status.json")["recommended_static"]["parameters"]
        return run_simulation(algorithm, mlfq, jobs, **parameters)
    registry = {**ALGORITHMS, **DEPLOYABLE_ALGORITHMS}
    if algorithm not in registry:
        raise ValueError("Choose an available scheduling algorithm.")
    scheduler, kwargs = registry[algorithm]
    return run_simulation(algorithm, scheduler, jobs, **kwargs)


@lru_cache(maxsize=1)
def _original_v5():
    from autoscheduler.dynamic import DYNAMIC_FEATURE_NAMES, DynamicRouterConfig
    from autoscheduler.model import load_model, load_model_metadata
    path = ROOT / DYNAMIC_V5_ARTIFACT
    if not path.exists():
        raise ValueError('Original v5 artifact is unavailable; select a static policy.')
    expected = read_json('results/real_source_dynamic_review_20261020/dashboard.json')['model_sha256']
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError('Original v5 artifact hash differs from its verified report.')
    config = DynamicRouterConfig(**load_model_metadata(path)['dynamic_config'])
    model = load_model(path, DYNAMIC_FEATURE_NAMES, expected_dynamic_config=config)
    return model, config


def _run_v5(jobs):
    from autoscheduler.dynamic import run_dynamic
    model, config = _original_v5()
    return run_dynamic(jobs, model, config)


@lru_cache(maxsize=1)
def _multi_demo():
    from autoscheduler.dynamic import DYNAMIC_FEATURE_NAMES
    from autoscheduler.model import load_model
    manifest = read_json('artifacts/dynamic_multi_policy_demo_20261020/manifest.json')
    if hashlib.sha256((ROOT / MULTI_DEMO_ARTIFACT).read_bytes()).hexdigest() != manifest['model_sha256']:
        raise ValueError('Demo artifact does not match its provenance manifest.')
    config = _original_v5()[1]
    return load_model(ROOT / MULTI_DEMO_ARTIFACT, DYNAMIC_FEATURE_NAMES, expected_dynamic_config=config), config


def _run_multi_demo(jobs):
    from copy import copy
    from autoscheduler.dynamic import run_dynamic
    base, config = _multi_demo()
    model, recorded = copy(base), []
    def predict(matrix):
        selections = base.predict(matrix)
        for action, costs in zip(selections, base.regressor.predict(matrix)):
            costs = dict(zip(base.policies, map(float, costs)))
            recorded.append({'proposed_action': action, 'predicted_costs': costs,
                'predicted_policy_benefits': {p: costs['No Switch'] - c for p, c in costs.items()}})
        return selections
    model.predict = predict
    router = run_dynamic(jobs, model, config)
    assert len(recorded) == len(router.decisions)
    router.recorded_predictions = recorded
    return router


def _frames(jobs, result):
    """Reconstruct playback membership and cumulative waiting without rescheduling."""
    by_pid = {p.pid: p for p in jobs}
    slices = {p.pid: [(start, end) for pid, start, end in result.timeline if pid == p.pid] for p in jobs}
    io_intervals = {}
    for job in jobs:
        intervals, threshold = [], 0
        for cpu, duration in zip(job.cpu_bursts, job.io_bursts):
            threshold += cpu
            used = 0
            for start, end in slices[job.pid]:
                if used < threshold <= used + end - start:
                    io_start = start + threshold - used
                    intervals.append((io_start, io_start + duration))
                    break
                used += end - start
        io_intervals[job.pid] = intervals
    frames = []
    for tick in range(result.makespan + 1):
        running = next((pid for pid, start, end in result.timeline if start <= tick < end), None)
        rows, ready, blocked = [], [], []
        for metric in sorted(result.process_metrics, key=lambda m: m.pid):
            job = by_pid[metric.pid]
            effective = min(tick, metric.completion_time)
            service = sum(max(0, min(effective, end) - start) for start, end in slices[job.pid] if start < effective)
            io_time = sum(max(0, min(effective, end) - start) for start, end in io_intervals[job.pid] if start < effective)
            if tick < job.arrival_time:
                state = "Not arrived"
            elif tick >= metric.completion_time:
                state = "Completed"
            elif any(start <= tick < end for start, end in io_intervals[job.pid]):
                state = "Blocked"
                blocked.append(job.pid)
            elif running == job.pid:
                state = "Running"
            else:
                state = "Ready"
                ready.append(job.pid)
            rows.append({"pid": job.pid, "arrival_time": job.arrival_time, "burst_time": job.burst_time,
                "priority": job.priority, "state": state,
                "waiting_time": max(0, effective - job.arrival_time - service - io_time),
                "response_time": metric.response_time if tick >= metric.start_time else None,
                "turnaround_time": metric.turnaround_time if tick >= metric.completion_time else None})
        frames.append({"tick": tick, "running": running, "ready": ready, "blocked": blocked, "processes": rows,
                       "completed": sum(p["state"] == "Completed" for p in rows)})
    return frames


@lru_cache(maxsize=24)
def simulation(workload="short_jobs", algorithm="Round Robin"):
    jobs = processes(workload)
    demo = workload == 'dynamic_multi_policy' and algorithm == DYNAMIC_V5_NAME
    router = (_run_multi_demo(jobs) if demo else _run_v5(jobs)) if algorithm == DYNAMIC_V5_NAME else None
    result = router.simulation if router else _run(jobs, algorithm)
    data = asdict(result)
    data.pop("process_metrics")
    frames = _frames(jobs, result)
    periods, transitions = [], []
    if router:
        active, start = router.initial_policy, 0
        for index, decision in enumerate(router.decisions):
            if decision.accepted:
                periods.append({"start": start, "end": decision.time, "policy": active})
                transitions.append({"decision_tick": decision.time, "effective_tick": decision.time,
                    "from_policy": active, "to_policy": decision.active, "reason": decision.reason,
                    "predicted_benefit": router.recorded_predictions[index]['predicted_policy_benefits'][decision.active] if demo else None})
                active, start = decision.active, decision.time
        periods.append({"start": start, "end": result.makespan, "policy": active})
        for frame in frames:
            frame["active_policy"] = next((p["policy"] for p in periods
                if p["start"] <= frame["tick"] < p["end"]), active)
    return {"workload": workload, "algorithm": algorithm, "metrics": data,
        "timeline": result.timeline, "processes": [asdict(m) for m in result.process_metrics],
        "frames": frames, "features": extract_features(jobs),
        "policy_timeline": periods, "policy_transitions": transitions,
        "routing_decisions": [{**asdict(d), **(router.recorded_predictions[i] if demo else {})} for i, d in enumerate(router.decisions)] if router else [],
        "dynamic_model": {"version": "experimental_demo" if demo else "v5", "artifact": MULTI_DEMO_ARTIFACT if demo else DYNAMIC_V5_ARTIFACT,
                          "label": MULTI_DEMO_LABEL if demo else "Original fitted Dynamic ML (v5)",
                          "switch_margin": (_multi_demo() if demo else _original_v5())[0].switch_margin,
                          "training_manifest": 'artifacts/dynamic_multi_policy_demo_20261020/manifest.json' if demo else None,
                          "configuration": asdict(_original_v5()[1]), "initial_policy": _original_v5()[1].initial_policy} if router else None,
        "reproducibility": {"workload_id": workload, "input_processes": [asdict(p) for p in jobs],
            "model_sha256": hashlib.sha256((ROOT / (MULTI_DEMO_ARTIFACT if demo else DYNAMIC_V5_ARTIFACT)).read_bytes()).hexdigest(),
            "api_request": "/api/simulation?" + urlencode({"workload": workload, "algorithm": algorithm})} if router else None,
        "queue_note": "Ready membership reconstructed from CPU service and I/O intervals; policy queue order is not exposed."}


@lru_cache(maxsize=3)
def comparison(workload="short_jobs"):
    jobs = processes(workload)
    references = compare_algorithms(jobs)
    results = {**references, "MLFQ": _run(jobs, "MLFQ"), "Tuned MLFQ": _run(jobs, "Tuned MLFQ"),
               (MULTI_DEMO_LABEL if workload == 'dynamic_multi_policy' else DYNAMIC_V5_NAME):
                   _run_multi_demo(jobs).simulation if workload == 'dynamic_multi_policy' else _run(jobs, DYNAMIC_V5_NAME)}
    rows = []
    for name, result in results.items():
        response = sorted(m.response_time for m in result.process_metrics)
        position = (len(response)-1)*.95
        low = int(position)
        p95 = response[low] + (response[min(low+1,len(response)-1)]-response[low])*(position-low)
        rows.append({"algorithm": name, "score": score_result_against_reference(result, references),
            "waiting": result.avg_waiting_time, "turnaround": result.avg_turnaround_time,
            "response": result.avg_response_time, "p95_response": p95, "utilization": result.cpu_utilization,
            "throughput": result.throughput, "context_switches": result.context_switches,
            "starvation": aggregate_fairness(result.process_metrics)["starvation_count"],
            "oracle_only": name in ("SJF", "SRTF")})
    return {"workload": workload, "scope": "One tiny hand-defined demo; not a research benchmark or model-selection dataset.",
            "score_reference": "Fixed bounds from the six traditional policies on this same workload; lower is better, values may exceed [0,1].",
            "results": sorted(rows, key=lambda row: row["score"])}
