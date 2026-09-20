"""Safe epoch-based routing for changing synthetic workloads."""

from __future__ import annotations

import copy
import csv
import json
import random
import tempfile
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, pvariance
from time import perf_counter_ns
from typing import Iterable

from autoscheduler.evaluation import ALGORITHMS, compare_algorithms, oracle_label, score_results
from autoscheduler.experiments import paired_bootstrap_ci
from autoscheduler.workloads import PROFILES, generate_workload
from simulator.process import Process
from simulator.simulator import SimulationResult, compute_metrics


DYNAMIC_FEATURE_NAMES = (
    "ready_count", "blocked_count", "remaining_cpu_mean", "remaining_cpu_variance",
    "priority_mean", "ready_wait_mean", "recent_arrivals", "io_return_ratio",
)
_POLICY_ORDER = tuple(ALGORITHMS)


@dataclass(frozen=True)
class DynamicRouterConfig:
    epoch_ticks: int = 10
    dwell_epochs: int = 1
    confidence_threshold: float = 0.6

    def __post_init__(self):
        if self.epoch_ticks <= 0 or self.dwell_epochs <= 0:
            raise ValueError("epoch_ticks and dwell_epochs must be positive")
        if not 0.0 <= self.confidence_threshold <= 1.0:
            raise ValueError("confidence_threshold must be between 0 and 1")


@dataclass(frozen=True)
class DynamicWorkload:
    seed: int
    phase_profiles: tuple[str, str, str]
    processes: tuple[Process, ...]


@dataclass
class _Ready:
    time: int
    sequence: int
    process: Process
    priority: int
    from_io: bool


@dataclass
class _State:
    pending: list[Process]
    ready: list[_Ready]
    blocked: list[tuple[int, Process, int, bool]]
    completed: list[Process]
    timeline: list[tuple[str, int, int]]
    current_time: int = 0
    sequence: int = 0
    last_pid: str | None = None
    recent_arrivals: int = 0
    io_returns: int = 0


@dataclass(frozen=True)
class RoutingDecision:
    time: int
    selected: str
    active: str
    confidence: float
    accepted: bool
    reason: str
    features: dict[str, float]
    transition_ms: float


@dataclass
class DynamicResult:
    simulation: SimulationResult
    initial_policy: str
    final_policy: str
    decisions: list[RoutingDecision]
    transition_p99_ms: float


def generate_dynamic_workload(
    seed: int,
    process_count: int | None = None,
    phase_profiles: tuple[str, str, str] | None = None,
) -> DynamicWorkload:
    """Create three continuing cohorts at t=0, 20, and 40."""
    randomizer = random.Random(seed)
    profiles = phase_profiles or tuple(randomizer.sample(PROFILES, 3))
    if len(profiles) != 3 or len(set(profiles)) != 3 or any(profile not in PROFILES for profile in profiles):
        raise ValueError("phase_profiles must contain three distinct known profiles")
    processes = []
    for phase, (profile, offset) in enumerate(zip(profiles, (0, 20, 40))):
        workload = generate_workload(profile, seed * 1_000 + phase, process_count)
        for index, process in enumerate(workload.processes, 1):
            processes.append(Process(
                pid=f"{profile}_{index}", arrival_time=process.arrival_time + offset,
                burst_time=process.burst_time, priority=process.priority,
                cpu_bursts=process.cpu_bursts, io_bursts=process.io_bursts,
            ))
    return DynamicWorkload(seed, profiles, tuple(processes))


def _new_state(processes: Iterable[Process]) -> _State:
    pending = sorted(copy.deepcopy(list(processes)), key=lambda process: (process.arrival_time, process.pid))
    if len({process.pid for process in pending}) != len(pending):
        raise ValueError("process IDs must be unique")
    for process in pending:
        process.reset()
    return _State(pending, [], [], [], [])


def _release(state: _State, until: int) -> None:
    events = []
    while state.pending and state.pending[0].arrival_time <= until:
        process = state.pending.pop(0)
        events.append((process.arrival_time, process.pid, process, process.priority, False))
        state.recent_arrivals += 1
    blocked = []
    for wake_time, process, priority, from_io in state.blocked:
        if wake_time <= until:
            events.append((wake_time, process.pid, process, priority, from_io))
            state.io_returns += int(from_io)
        else:
            blocked.append((wake_time, process, priority, from_io))
    state.blocked = blocked
    for ready_time, _, process, priority, from_io in sorted(events, key=lambda event: (event[0], event[1])):
        state.ready.append(_Ready(ready_time, state.sequence, process, priority, from_io))
        state.sequence += 1


def _ready_key(item: _Ready, policy: str, now: int, aging_interval: int) -> tuple:
    if policy == "Round Robin":
        return (item.sequence,)
    if policy == "Priority RR":
        return (max(1, item.priority - (now - item.time) // aging_interval), item.sequence)
    if policy == "SJF":
        return (item.process.burst_time, item.time, item.process.pid)
    if policy == "SRTF":
        return (item.process.remaining_time, item.time, item.process.pid)
    if policy == "Priority":
        return (item.process.priority, item.time, item.process.pid)
    return (item.time, item.process.pid)


def _rebuild_ready(state: _State, policy: str, priority_rr_config: dict) -> None:
    state.ready.sort(key=lambda item: _ready_key(item, policy, state.current_time, priority_rr_config["aging_interval"]))


def _policy_config(priority_rr_config: dict | None) -> dict:
    return {**ALGORITHMS["Priority RR"][1], **(priority_rr_config or {})}


def _dispatch(state: _State, policy: str, priority_rr_config: dict) -> None:
    _release(state, state.current_time)
    if not state.ready:
        times = [process.arrival_time for process in state.pending]
        times.extend(wake_time for wake_time, *_ in state.blocked)
        if not times:
            return
        state.current_time = min(times)
        _release(state, state.current_time)
    _rebuild_ready(state, policy, priority_rr_config)
    ready = state.ready.pop(0)
    process = ready.process
    switch_cost = priority_rr_config["context_switch_cost"] if policy == "Priority RR" else 0
    if state.last_pid is not None and state.last_pid != process.pid and switch_cost:
        state.timeline.append(("CS", state.current_time, state.current_time + switch_cost))
        state.current_time += switch_cost
        _release(state, state.current_time)
    if ready.from_io:
        process.post_io_response_times.append(state.current_time - ready.time)
    if process.start_time == -1:
        process.start_time = state.current_time
    while process.remaining_time:
        run_for = process.remaining_time
        if policy in {"Round Robin", "Priority RR"}:
            run_for = min(run_for, priority_rr_config["quantum"])
        elif policy == "SRTF":
            next_events = [state.pending[0].arrival_time] if state.pending else []
            next_events.extend(wake_time for wake_time, *_ in state.blocked)
            if next_events:
                run_for = min(run_for, min(next_events) - state.current_time)
        end_time = state.current_time + run_for
        if policy == "SRTF" and state.timeline and state.timeline[-1][0] == process.pid and state.timeline[-1][2] == state.current_time:
            state.timeline[-1] = (process.pid, state.timeline[-1][1], end_time)
        else:
            state.timeline.append((process.pid, state.current_time, end_time))
        process.remaining_time -= run_for
        state.current_time = end_time
        state.last_pid = process.pid
        _release(state, state.current_time)
        if policy != "SRTF" or not process.remaining_time:
            break
        if any(item.process.remaining_time < process.remaining_time for item in state.ready):
            break
    if process.remaining_time:
        state.ready.append(_Ready(state.current_time, state.sequence, process, process.priority, False))
        state.sequence += 1
    elif process.burst_index < len(process.cpu_bursts) - 1:
        wake_time = state.current_time + process.io_bursts[process.burst_index]
        process.burst_index += 1
        process.remaining_time = process.cpu_bursts[process.burst_index]
        state.blocked.append((wake_time, process, max(1, process.priority - 1), True))
    else:
        process.completion_time = state.current_time
        state.completed.append(process)


def _run_to_completion(state: _State, policy: str, priority_rr_config: dict) -> None:
    while state.pending or state.ready or state.blocked:
        _dispatch(state, policy, priority_rr_config)


def _simulation(state: _State, algorithm: str) -> SimulationResult:
    metrics = compute_metrics(state.completed)
    count = len(metrics)
    busy = sum(end - start for pid, start, end in state.timeline if pid != "CS")
    switch_time = sum(end - start for pid, start, end in state.timeline if pid == "CS")
    makespan = max((end for _, _, end in state.timeline), default=0)
    process_timeline = [entry for entry in state.timeline if entry[0] != "CS"]
    return SimulationResult(
        algorithm, metrics, state.timeline,
        sum(metric.turnaround_time for metric in metrics) / count if count else 0.0,
        sum(metric.waiting_time for metric in metrics) / count if count else 0.0,
        sum(metric.response_time for metric in metrics) / count if count else 0.0,
        busy / makespan if makespan else 0.0, count / makespan if makespan else 0.0,
        makespan, makespan - busy - switch_time,
        sum(previous[0] != current[0] for previous, current in zip(process_timeline, process_timeline[1:])),
        switch_time, max((metric.waiting_time for metric in metrics), default=0),
    )


def extract_dynamic_features(state: _State) -> dict[str, float]:
    candidates = [item.process for item in state.ready] + [process for _, process, _, _ in state.blocked]
    if not candidates:
        return dict.fromkeys(DYNAMIC_FEATURE_NAMES, 0.0)
    remaining = [process.remaining_time for process in candidates]
    priorities = [process.priority for process in candidates]
    waits = [max(0, state.current_time - item.time) for item in state.ready]
    return {
        "ready_count": float(len(state.ready)), "blocked_count": float(len(state.blocked)),
        "remaining_cpu_mean": mean(remaining), "remaining_cpu_variance": pvariance(remaining),
        "priority_mean": mean(priorities), "ready_wait_mean": mean(waits) if waits else 0.0,
        "recent_arrivals": float(state.recent_arrivals),
        "io_return_ratio": state.io_returns / max(1, state.recent_arrivals + state.io_returns),
    }


def _prediction(model, features: dict[str, float]) -> tuple[str, float]:
    row = [[features[name] for name in DYNAMIC_FEATURE_NAMES]]
    selected = str(model.predict(row)[0])
    if selected not in ALGORITHMS:
        raise ValueError(f"model selected unknown algorithm: {selected}")
    if hasattr(model, "predict_proba") and hasattr(model, "classes_"):
        probabilities = model.predict_proba(row)[0]
        confidence = float(max(probabilities))
    else:
        confidence = 1.0
    return selected, confidence


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low, high = int(position), min(int(position) + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def run_dynamic(
    processes: Iterable[Process], model, config: DynamicRouterConfig = DynamicRouterConfig(),
    priority_rr_config: dict | None = None,
) -> DynamicResult:
    """Run safe routing; review epochs take effect at next dispatch boundary."""
    state = _new_state(processes)
    rr_config = _policy_config(priority_rr_config)
    active = "Round Robin"
    next_epoch, last_switch = config.epoch_ticks, 0
    decisions: list[RoutingDecision] = []
    while state.pending or state.ready or state.blocked:
        _release(state, state.current_time)
        if not state.ready:
            times = [process.arrival_time for process in state.pending]
            times.extend(wake_time for wake_time, *_ in state.blocked)
            if times:
                state.current_time = min(times)
                _release(state, state.current_time)
        if state.current_time >= next_epoch and state.ready:
            while next_epoch <= state.current_time:
                next_epoch += config.epoch_ticks
            started = perf_counter_ns()
            features = extract_dynamic_features(state)
            selected, confidence = _prediction(model, features)
            dwell_elapsed = state.current_time - last_switch >= config.dwell_epochs * config.epoch_ticks
            accepted = selected != active and confidence >= config.confidence_threshold and dwell_elapsed
            reason = (
                "accepted" if accepted else "same_policy" if selected == active else
                "low_confidence" if confidence < config.confidence_threshold else "dwell_blocked"
            )
            if accepted:
                active = selected
                last_switch = state.current_time
                _rebuild_ready(state, active, rr_config)
            decisions.append(RoutingDecision(
                state.current_time, selected, active, confidence, accepted, reason, features,
                (perf_counter_ns() - started) / 1_000_000,
            ))
            state.recent_arrivals = state.io_returns = 0
        _dispatch(state, active, rr_config)
    return DynamicResult(_simulation(state, "Dynamic Adaptive"), "Round Robin", active, decisions,
                         _percentile([decision.transition_ms for decision in decisions], 0.99))


def _counterfactual_label(state: _State, epoch_ticks: int, priority_rr_config: dict) -> tuple[str, dict[str, float]]:
    results = {}
    boundary = state.current_time + epoch_ticks
    for policy in ALGORITHMS:
        trial = copy.deepcopy(state)
        while (trial.pending or trial.ready or trial.blocked) and trial.current_time < boundary:
            _dispatch(trial, policy, priority_rr_config)
        _run_to_completion(trial, "Round Robin", priority_rr_config)
        results[policy] = _simulation(trial, policy)
    return oracle_label(results)


def _training_states(processes: Iterable[Process], config: DynamicRouterConfig, priority_rr_config: dict) -> list[_State]:
    state, states, next_epoch = _new_state(processes), [], config.epoch_ticks
    while state.pending or state.ready or state.blocked:
        _release(state, state.current_time)
        if not state.ready:
            times = [process.arrival_time for process in state.pending]
            times.extend(wake_time for wake_time, *_ in state.blocked)
            if times:
                state.current_time = min(times)
                _release(state, state.current_time)
        if state.current_time >= next_epoch and state.ready:
            while next_epoch <= state.current_time:
                next_epoch += config.epoch_ticks
            states.append(copy.deepcopy(state))
            state.recent_arrivals = state.io_returns = 0
        _dispatch(state, "Round Robin", priority_rr_config)
    return states


def build_dynamic_dataset(
    traces: int = 100, seed: int = 42, config: DynamicRouterConfig = DynamicRouterConfig(),
    priority_rr_config: dict | None = None,
) -> list[dict]:
    if traces <= 0:
        raise ValueError("traces must be positive")
    rr_config = _policy_config(priority_rr_config)
    rows = []
    for index in range(traces):
        workload = generate_dynamic_workload(seed * 1_000_000 + index)
        for epoch, state in enumerate(_training_states(workload.processes, config, rr_config)):
            label, scores = _counterfactual_label(state, config.epoch_ticks, rr_config)
            row = extract_dynamic_features(state)
            row.update({"seed": workload.seed, "epoch": epoch, "profiles": "/".join(workload.phase_profiles), "label": label})
            row.update({f"score_{name.lower().replace(' ', '_')}": score for name, score in scores.items()})
            rows.append(row)
    if not rows:
        raise ValueError("dynamic traces produced no decision epochs")
    return rows


def evaluate_dynamic(
    model, traces: int = 1_000, seed: int = 2026, config: DynamicRouterConfig = DynamicRouterConfig(),
    priority_rr_config: dict | None = None,
) -> tuple[list[dict], dict]:
    if traces <= 0:
        raise ValueError("traces must be positive")
    rows = []
    rr_config = _policy_config(priority_rr_config)
    for index in range(traces):
        workload = generate_dynamic_workload(seed * 1_000_000 + index)
        static = compare_algorithms(workload.processes, rr_config)
        adaptive = run_dynamic(workload.processes, model, config, rr_config)
        scores = score_results({**static, "Adaptive": adaptive.simulation})
        rr_response = _percentile([metric.response_time for metric in static["Round Robin"].process_metrics], 0.95)
        adaptive_response = _percentile([metric.response_time for metric in adaptive.simulation.process_metrics], 0.95)
        row = {
            "seed": workload.seed, "profiles": "/".join(workload.phase_profiles),
            "p95_response_round_robin": rr_response, "p95_response_adaptive": adaptive_response,
            "p95_response_difference": adaptive_response - rr_response,
            "weighted_score_round_robin": scores["Round Robin"], "weighted_score_adaptive": scores["Adaptive"],
            "weighted_score_difference": scores["Adaptive"] - scores["Round Robin"],
            "transition_p99_ms": adaptive.transition_p99_ms,
            "accepted_switches": sum(decision.accepted for decision in adaptive.decisions),
            "held_decisions": sum(not decision.accepted for decision in adaptive.decisions),
            "dwell_blocked_decisions": sum(decision.reason == "dwell_blocked" for decision in adaptive.decisions),
            "low_confidence_decisions": sum(decision.reason == "low_confidence" for decision in adaptive.decisions),
            "mean_confidence": mean([decision.confidence for decision in adaptive.decisions] or [0.0]),
        }
        row.update({f"score_{name.lower().replace(' ', '_')}": score for name, score in scores.items() if name != "Adaptive"})
        rows.append(row)
    p95_ci = paired_bootstrap_ci([row["p95_response_difference"] for row in rows])
    score_ci = paired_bootstrap_ci([row["weighted_score_difference"] for row in rows])
    summary = {
        "traces": traces, "seed": seed, "config": config.__dict__,
        "p95_response_difference": p95_ci, "weighted_score_difference": score_ci,
        "mean_transition_p99_ms": mean(row["transition_p99_ms"] for row in rows),
        "max_transition_p99_ms": max(row["transition_p99_ms"] for row in rows),
        "mean_accepted_switches": mean(row["accepted_switches"] for row in rows),
        "mean_held_decisions": mean(row["held_decisions"] for row in rows),
        "mean_dwell_blocked_decisions": mean(row["dwell_blocked_decisions"] for row in rows),
        "mean_low_confidence_decisions": mean(row["low_confidence_decisions"] for row in rows),
        "mean_confidence": mean(row["mean_confidence"] for row in rows),
        "mean_static_scores": {
            name: mean(row[f"score_{name.lower().replace(' ', '_')}"] for row in rows)
            for name in ALGORITHMS
        },
    }
    summary["per_transition"] = {
        profiles: {
            "traces": len(group),
            "mean_p95_response_difference": mean(row["p95_response_difference"] for row in group),
            "mean_weighted_score_difference": mean(row["weighted_score_difference"] for row in group),
        }
        for profiles in sorted({row["profiles"] for row in rows})
        for group in ([row for row in rows if row["profiles"] == profiles],)
    }
    summary["p95_response_gate"] = p95_ci["ci_high"] < 0
    summary["weighted_score_gate"] = score_ci["ci_high"] <= 0
    summary["latency_gate"] = summary["max_transition_p99_ms"] < 10.0
    summary["eligible"] = all(summary[key] for key in ("p95_response_gate", "weighted_score_gate", "latency_gate"))
    return rows, summary


def save_dynamic_evaluation(rows: list[dict], summary: dict, output_dir: str | Path) -> None:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    with (output / "dynamic_evaluation.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)
    (output / "dynamic_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    import os
    cache_dir = Path(".cache/matplotlib").resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ["MPLCONFIGDIR"] = str(cache_dir)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    figure, axes = plt.subplots(1, 2, figsize=(9, 4))
    axes[0].hist([row["p95_response_difference"] for row in rows])
    axes[0].set_title("Adaptive minus RR P95 response")
    axes[1].hist([row["weighted_score_difference"] for row in rows])
    axes[1].set_title("Adaptive minus RR score")
    figure.tight_layout()
    figure.savefig(output / "dynamic_diagnostics.png")
    plt.close(figure)


def tune_dynamic_config(
    traces: int = 20, seed: int = 42, priority_rr_config: dict | None = None,
) -> dict:
    """Tune only on development traces, then return a frozen router configuration."""
    from autoscheduler.model import load_model, train_model

    if traces <= 0:
        raise ValueError("traces must be positive")
    candidates = []
    rr_config = _policy_config(priority_rr_config)
    with tempfile.TemporaryDirectory() as directory:
        for index, (epoch, dwell, confidence) in enumerate(
            (epoch, dwell, confidence)
            for epoch in (5, 10, 20)
            for dwell in (1, 2, 3)
            for confidence in (0.0, 0.6, 0.8)
        ):
            config = DynamicRouterConfig(epoch, dwell, confidence)
            rows = build_dynamic_dataset(traces, seed, config, rr_config)
            path = Path(directory) / f"candidate_{index}.joblib"
            train_model(rows, path, seed, rr_config, DYNAMIC_FEATURE_NAMES, {"dynamic_config": config.__dict__})
            _, summary = evaluate_dynamic(
                load_model(path, DYNAMIC_FEATURE_NAMES), traces, seed + 1_000_000, config, rr_config
            )
            candidates.append({"config": config.__dict__, **summary})
    eligible = [candidate for candidate in candidates if candidate["weighted_score_gate"]]
    pool = eligible or candidates
    selected = min(
        pool,
        key=lambda candidate: (
            candidate["p95_response_difference"]["mean"],
            candidate["config"]["epoch_ticks"],
            candidate["config"]["dwell_epochs"],
            -candidate["config"]["confidence_threshold"],
        ),
    )
    return {
        "seed": seed, "traces": traces, "candidates": candidates,
        "score_constraint_met": bool(eligible), "selected": selected["config"],
    }
