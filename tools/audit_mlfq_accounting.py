"""Reproduce MLFQ accounting diagnostics without training or changing policy code.

Run: .venv/bin/python tools/audit_mlfq_accounting.py --output /tmp/new-audit.json
The original 1,000 seed-2026 workloads and score weights remain unchanged.
Equal-cost variants are sensitivity checks, outside the frozen policy contract.
"""

import argparse
from collections import Counter, defaultdict
from functools import partial
import json
from pathlib import Path
import random
from statistics import mean
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autoscheduler.dynamic import (
    _dispatch, _new_state, _run_to_completion, _simulation,
    extract_dynamic_features, generate_dynamic_workload, _percentile,
)
from autoscheduler.evaluation import (
    ALGORITHMS, DEPLOYABLE_ALGORITHMS, SCORE_WEIGHTS,
    run_algorithm, score_result_against_reference,
)
from simulator.engine import simulate
from simulator.process import Process
from simulator.simulator import run_simulation

ELIGIBLE = tuple(DEPLOYABLE_ALGORITHMS)
SEVEN = tuple(dict.fromkeys((*ALGORITHMS, *ELIGIBLE)))
BOUNDS = {"eligible5": ELIGIBLE, "historical6": tuple(ALGORITHMS), "static7": SEVEN}
CONFIGS = {
    "FCFS": ("fcfs", {}), "SJF": ("sjf", {}),
    "SRTF": ("srtf", {"preemptive": True}),
    "Round Robin": ("rr", {"quantum": 2}), "Priority": ("priority", {}),
    "Priority RR": ("priority_rr", {"quantum": 2, "aging_interval": 8}),
    "MLFQ": ("mlfq", {"queue_quanta": (2, 4, 8), "aging_threshold": 20}),
}


def verify_accounting():
    rng = random.Random(912850)
    cases = 0
    for policy in SEVEN:
        for case in range(250):
            processes = []
            for index in range(rng.randint(1, 12)):
                bursts = tuple(rng.randint(1, 25) for _ in range(rng.randint(1, 4)))
                processes.append(Process(
                    str(index), rng.randint(0, 40), sum(bursts), rng.randint(0, 8),
                    cpu_bursts=bursts, io_bursts=tuple(rng.randint(1, 30) for _ in bursts[1:]),
                ))
            expected = run_algorithm(policy, processes)
            state = _new_state(processes)
            _run_to_completion(state, policy, ALGORITHMS["Priority RR"][1])
            actual = _simulation(state, policy)
            assert actual.timeline == expected.timeline, (policy, case, "timeline")
            assert actual.process_metrics == expected.process_metrics, (policy, case, "metrics")
            service, clock, gaps = Counter(), 0, 0
            for pid, start, end in actual.timeline:
                assert start >= clock and end > start, (policy, case, "interval")
                gaps += start - clock
                clock = end
                if pid != "CS":
                    service[pid] += end - start
            assert service == Counter({p.pid: p.burst_time for p in processes})
            assert gaps == actual.idle_time
            assert sum(service.values()) + gaps + actual.context_switch_time == actual.makespan
            assert actual.context_switch_time == (actual.context_switches if policy == "Priority RR" else 0)
            assert all(metric.waiting_time >= 0 for metric in actual.process_metrics)
            cases += 1
    return {"workload_policy_cases": cases, "workloads_per_policy": 250, "random_seed": 912850,
            "checks": ["exact_static_dynamic_timeline_and_process_metrics", "per_pid_cpu_service_conservation",
                       "positive_nonoverlapping_timeline", "independent_idle_gap_accounting",
                       "busy_plus_idle_plus_switch_equals_makespan",
                       "switch_charges_match_frozen_policy_configuration", "nonnegative_waiting"]}


def sensitivity(cost):
    values = {bound: defaultdict(list) for bound in BOUNDS}
    wins, degenerate = ({bound: Counter() for bound in BOUNDS} for _ in range(2))
    raw_delta, rr_winners, zero_examples = defaultdict(list), [], []
    zero_count = zero_workloads = 0
    for index in range(1000):
        workload = generate_dynamic_workload(2026000000 + index)
        results = {}
        for policy in SEVEN:
            if cost is None:
                results[policy] = run_algorithm(policy, workload.processes)
            else:
                engine, parameters = CONFIGS[policy]
                scheduler = partial(simulate, policy=engine, context_switch_cost=cost, **parameters)
                results[policy] = run_simulation(policy, scheduler, list(workload.processes))
        timeline = results["MLFQ"].timeline
        zeros = [(position, item) for position, item in enumerate(timeline) if item[1] == item[2]]
        if zeros:
            zero_workloads += 1
            zero_count += len(zeros)
            if len(zero_examples) < 3:
                position, _ = zeros[0]
                zero_examples.append({"seed": workload.seed, "timeline": timeline[max(0, position - 2):position + 3]})
        for metric in SCORE_WEIGHTS:
            raw_delta[metric].append(getattr(results["MLFQ"], metric) - getattr(results["Round Robin"], metric))
        score_sets = {}
        for bound, names in BOUNDS.items():
            for metric in SCORE_WEIGHTS:
                samples = [getattr(results[policy], metric) for policy in names]
                degenerate[bound][metric] += int(max(samples) == min(samples))
            scores = {policy: score_result_against_reference(results[policy], results, names) for policy in ELIGIBLE}
            score_sets[bound] = scores
            for policy in ELIGIBLE:
                values[bound][policy].append(scores[policy])
                wins[bound][policy] += int(abs(scores[policy] - min(scores.values())) <= 1e-12)
        if cost is None and score_sets["eligible5"]["Round Robin"] < score_sets["eligible5"]["MLFQ"]:
            rr_winners.append({"seed": workload.seed, "weighted_scores": score_sets,
                               "raw_metrics": {policy: {metric: getattr(results[policy], metric) for metric in SCORE_WEIGHTS}
                                               for policy in ("Round Robin", "MLFQ")},
                               "mlfq_minus_rr_eligible5_score": score_sets["eligible5"]["MLFQ"] - score_sets["eligible5"]["Round Robin"]})
    summaries = {}
    for bound, names in BOUNDS.items():
        means = {policy: mean(values[bound][policy]) for policy in ELIGIBLE}
        summaries[bound] = {"reference_policies": names, "mean_scores": means,
                            "wins": {policy: wins[bound][policy] for policy in ELIGIBLE},
                            "mean_mlfq_minus_rr_score": means["MLFQ"] - means["Round Robin"],
                            "degenerate_ranges": dict(degenerate[bound])}
    return {"bounds": summaries, "raw_mean_mlfq_minus_rr": {metric: mean(items) for metric, items in raw_delta.items()},
            "mlfq_zero_service_intervals": {"interval_count": zero_count, "affected_workloads": zero_workloads,
                                             "examples": zero_examples, "measured_from_engine_rerun": True}}, rr_winners


def feature_aging():
    processes = [Process("A", 0, 3)] + [Process(f"P{tick}", tick, 1) for tick in range(1, 22)]
    processes.append(Process("P23", 23, 1))
    state = _new_state(processes)
    while state.current_time < 23:
        _dispatch(state, "MLFQ", ALGORITHMS["Priority RR"][1])
    last_service = max(end for pid, _, end in state.timeline if pid == "A")
    return {"processes": "A(arrival0,cpu3); P1..P21(arrival1..21,cpu1); P23(arrival23,cpu1)",
            "state": "Dispatch MLFQ until current_time23. A last served[0,2], remained ready continuously since2, promoted at22.",
            "expected_continuous_ready_wait": state.current_time - last_service,
            "reported_ready_wait_max": extract_dynamic_features(state, "MLFQ")["ready_wait_max"],
            "cause": "_age_mlfq resets _Ready.time for aging; extractor uses that timestamp for ready waiting. Static completion metrics are unaffected."}


def parameter_sensitivity():
    """Predeclared diagnostic variants; never choose parameters on this audit."""
    settings = [(f"RR_q{q}", "rr", {"quantum": q}) for q in (1,2,4,8)]
    settings += [(f"MLFQ_{quanta}_aging{aging}", "mlfq",
                  {"queue_quanta": quanta, "aging_threshold": aging})
                 for quanta in ((1,2,4),(2,4,8),(4,8,16)) for aging in (10,20,40)]
    groups = {name: [] for name,_,_ in settings}
    for index in range(1000):
        workload = generate_dynamic_workload(2026000000 + index)
        refs = {name:run_algorithm(name,workload.processes) for name in ALGORITHMS}
        baseline = run_algorithm("MLFQ",workload.processes)
        baseline_score = score_result_against_reference(baseline,refs)
        for name,policy,parameters in settings:
            result = run_simulation(name,partial(simulate,policy=policy,**parameters),list(workload.processes))
            score = score_result_against_reference(result,refs)
            groups[name].append({"score":score,"difference":score-baseline_score,
                                "p95":_percentile([m.response_time for m in result.process_metrics],.95)})
    return {"status":"POST_HOC_PARAMETER_SENSITIVITY_NOT_TUNING", "reference":"unchanged_frozen_six_bounds",
            "frozen_parameters_unchanged":True,
            "variants":{name:{"mean_score":mean(r["score"] for r in rows),
                              "mean_p95":mean(r["p95"] for r in rows),
                              "wins_against_frozen_mlfq":sum(r["difference"] < -1e-12 for r in rows)}
                        for name,rows in groups.items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("/tmp/mlfq-accounting-reproduced.json"))
    parser.add_argument("--parameter-scan-only", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists; choose a fresh path")
    if args.parameter_scan_only:
        report = parameter_sensitivity()
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with args.output.open("x",encoding="utf-8") as target:
            json.dump(report,target,indent=2)
        print(f"Saved parameter sensitivity: {args.output}")
        return
    report = {"status": "DIAGNOSTIC_NO_RETRAINING_NO_PRODUCTION_CHANGES", "traces": 1000, "seed": 2026,
              "score_weights": SCORE_WEIGHTS, "wins_count_exact_optimal_ties_for_each_policy": True,
              "parity_and_accounting": verify_accounting(), "scenarios": {}}
    for scenario, cost in (("frozen_asymmetric", None), ("equal_cost_0", 0), ("equal_cost_1", 1)):
        print(f"Auditing {scenario}", flush=True)
        report["scenarios"][scenario], winners = sensitivity(cost)
        if cost is None:
            report["default_eligible5_rr_winners"] = winners
    report["findings"] = {
        "frozen_switch_costs": "Only Priority RR charges one tick; others charge zero, as the frozen contract specifies.",
        "equal_cost_1_caveat": "Nonzero-cost MLFQ selects before overhead without reselecting after arrivals/promotions during overhead. Stale aging deadlines can force zero-service dispatches, last_pid updates, and another switch charge. This variant is outside frozen MLFQ cost0 and is not an independently validated alternative policy.",
        "feature_aging_repro": feature_aging(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as target:
        json.dump(report, target, indent=2)
        target.write("\n")
    print(f"Saved diagnostics: {args.output}")


if __name__ == "__main__":
    main()
