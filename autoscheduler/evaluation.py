"""Static scheduler comparison and oracle labeling."""

from __future__ import annotations

from typing import Iterable

from scheduler.fcfs import fcfs
from scheduler.mlfq import mlfq
from scheduler.priority import priority_scheduling
from scheduler.priority_rr import priority_round_robin
from scheduler.round_robin import round_robin
from scheduler.sjf import sjf
from scheduler.srtf import srtf
from simulator.process import Process
from simulator.simulator import SimulationResult, run_simulation


ALGORITHMS = {
    "FCFS": (fcfs, {}),
    "SJF": (sjf, {}),
    "SRTF": (srtf, {}),
    "Round Robin": (round_robin, {"quantum": 2}),
    "Priority": (priority_scheduling, {}),
    "Priority RR": (
        priority_round_robin,
        {"quantum": 2, "aging_interval": 8, "context_switch_cost": 1},
    ),
}

SELECTOR_ALGORITHMS = ALGORITHMS

# The historical six-policy simulation registry intentionally includes oracles.
DEPLOYABLE_ALGORITHMS = {
    name: ALGORITHMS[name] for name in ("FCFS", "Round Robin", "Priority", "Priority RR")
}
DEPLOYABLE_ALGORITHMS["MLFQ"] = (mlfq, {"quanta": (2, 4, 8), "aging_threshold": 20})

SCORE_WEIGHTS = {
    "avg_waiting_time": 0.30,
    "avg_response_time": 0.25,
    "avg_turnaround_time": 0.20,
    "cpu_utilization": 0.15,
    "throughput": 0.10,
}


def run_algorithm(
    name: str, processes: Iterable[Process], priority_rr_config: dict | None = None
) -> SimulationResult:
    scheduler, kwargs = {**ALGORITHMS, **DEPLOYABLE_ALGORITHMS}[name]
    if name == "Priority RR" and priority_rr_config:
        kwargs = {**kwargs, **priority_rr_config}
    return run_simulation(name, scheduler, list(processes), **kwargs)


def compare_algorithms(
    processes: Iterable[Process], priority_rr_config: dict | None = None, algorithms=None
) -> dict[str, SimulationResult]:
    processes = list(processes)
    return {
        name: run_algorithm(name, processes, priority_rr_config)
        for name in (algorithms or ALGORITHMS)
    }


def _normalize(values: dict[str, float], maximize: bool = False) -> dict[str, float]:
    low, high = min(values.values()), max(values.values())
    if high == low:
        return {name: 0.0 for name in values}
    if maximize:
        return {name: (high - value) / (high - low) for name, value in values.items()}
    return {name: (value - low) / (high - low) for name, value in values.items()}


def score_results(results: dict[str, SimulationResult]) -> dict[str, float]:
    """Return lower-is-better weighted scores normalized within one workload."""
    scores = dict.fromkeys(results, 0.0)
    for metric, weight in SCORE_WEIGHTS.items():
        values = {name: getattr(result, metric) for name, result in results.items()}
        normalized = _normalize(values, maximize=metric in {"cpu_utilization", "throughput"})
        for name, value in normalized.items():
            scores[name] += weight * value
    return scores


def score_result_against_reference(
    result: SimulationResult,
    reference_results: dict[str, SimulationResult],
    reference_names=None,
) -> float:
    """Score one result using metric bounds frozen by reference policies."""
    names = tuple(reference_names or reference_results)
    score = 0.0
    for metric, weight in SCORE_WEIGHTS.items():
        values = [getattr(reference_results[name], metric) for name in names]
        low, high = min(values), max(values)
        if high == low:
            continue
        value = getattr(result, metric)
        normalized = ((high - value) if metric in {"cpu_utilization", "throughput"} else (value - low)) / (high - low)
        score += weight * normalized
    return score


def oracle_label(results: dict[str, SimulationResult]) -> tuple[str, dict[str, float]]:
    scores = score_results(results)
    order = tuple(dict.fromkeys((*ALGORITHMS, *DEPLOYABLE_ALGORITHMS)))
    label = min(results, key=lambda name: (scores[name], order.index(name)))
    return label, scores
