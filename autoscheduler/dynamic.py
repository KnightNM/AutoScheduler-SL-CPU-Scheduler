"""Safe epoch-based routing for changing synthetic workloads."""

from __future__ import annotations

import copy
import csv
import json
import random
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, pvariance
from time import perf_counter_ns
from typing import Iterable

from autoscheduler.evaluation import (
    ALGORITHMS, DEPLOYABLE_ALGORITHMS, compare_algorithms,
    score_result_against_reference,
)
from autoscheduler.experiments import paired_bootstrap_ci
from autoscheduler.workloads import PROFILES, generate_workload
from simulator.process import Process
from simulator.simulator import SimulationResult, compute_metrics


DYNAMIC_FEATURE_NAMES = (
    "ready_count", "blocked_count", "completed_burst_mean", "completed_burst_variance",
    "observed_service_mean", "observed_service_variance", "priority_mean",
    "ready_wait_mean", "ready_wait_max", "recent_arrivals", "io_returns", "io_return_ratio",
    "active_policy_index", "dwell_remaining_ticks",
    "first_service_ready_count", "first_service_wait_max", "ready_wait_p50", "ready_wait_p95",
    "arrival_quiet_ticks",
)
DYNAMIC_POLICY_NAMES = tuple(DEPLOYABLE_ALGORITHMS)
DYNAMIC_SCHEMA_VERSION = 5


@dataclass(frozen=True)
class DynamicRouterConfig:
    epoch_ticks: int = 10
    dwell_epochs: int = 1
    confidence_threshold: float = 0.6
    policy_track: str = "realistic"
    initial_policy: str = "Round Robin"
    fallback_policy: str | None = None
    label_horizon_ticks: int | None = None
    label_continuation: str = "MLFQ"
    first_service_protection: bool = True
    explicit_no_switch: bool = False
    mlfq_quanta: tuple[int, ...] = (2, 4, 8)
    mlfq_aging_threshold: int = 20
    response_tail_protection: bool = False
    arrival_quiet_dwell_periods: int = 1

    def __post_init__(self):
        object.__setattr__(self, "mlfq_quanta", tuple(self.mlfq_quanta))
        if len(self.mlfq_quanta) != 3 or any(q <= 0 for q in self.mlfq_quanta) or self.mlfq_aging_threshold <= 0:
            raise ValueError("MLFQ requires three positive quanta and a positive aging threshold")
        if self.epoch_ticks <= 0 or self.dwell_epochs <= 0:
            raise ValueError("epoch_ticks and dwell_epochs must be positive")
        if type(self.arrival_quiet_dwell_periods) is not int or self.arrival_quiet_dwell_periods < 1:
            raise ValueError("arrival quiet dwell periods must be a positive integer")
        if not 0.0 <= self.confidence_threshold <= 1.0:
            raise ValueError("confidence_threshold must be between 0 and 1")
        if self.policy_track not in {"realistic", "oracle_simulation"}:
            raise ValueError("policy_track must be realistic or oracle_simulation")
        policies = DYNAMIC_POLICY_NAMES if self.policy_track == "realistic" else tuple(ALGORITHMS)
        if self.initial_policy not in policies or (self.fallback_policy is not None and self.fallback_policy not in policies):
            raise ValueError("startup and fallback must be eligible policies")
        if self.label_continuation not in {"MLFQ", "Round Robin"}:
            raise ValueError("label continuation must be MLFQ or explicit historical Round Robin")
        if self.label_horizon_ticks is not None and self.label_horizon_ticks < self.epoch_ticks * self.dwell_epochs:
            raise ValueError("label horizon cannot be shorter than minimum dwell")
        if self.response_tail_protection and (
            not self.first_service_protection or self.policy_track != "realistic" or self.fallback_policy != "MLFQ"
            or self.label_continuation != "MLFQ"
            or self.effective_label_horizon != self.epoch_ticks * self.dwell_epochs
        ):
            raise ValueError("tail protection requires first-service protection, realistic MLFQ fallback/continuation and a minimum-dwell horizon")

    @property
    def effective_label_horizon(self) -> int:
        return self.label_horizon_ticks or self.epoch_ticks * self.dwell_epochs


def dynamic_policy_names(config: DynamicRouterConfig) -> tuple[str, ...]:
    return DYNAMIC_POLICY_NAMES if config.policy_track == "realistic" else tuple(ALGORITHMS)


def dynamic_action_names(config: DynamicRouterConfig) -> tuple[str, ...]:
    return (*dynamic_policy_names(config), "No Switch") if config.explicit_no_switch else dynamic_policy_names(config)


def _protected(features, active, selected, config):
    return (config.first_service_protection and active == "MLFQ" and selected != active
            and features["first_service_ready_count"] > 0)


def _resolve_action(action, active):
    return active if action == "No Switch" else action


def _tail_action(features, active, selected, config):
    """Bound excursions to the training horizon; assess observed pressure only."""
    if not config.response_tail_protection:
        return selected, None
    if active != "MLFQ":
        if features["dwell_remaining_ticks"] <= 0:
            return "MLFQ", "excursion_expired"
        unserved = features["first_service_ready_count"]
        urgent = unserved > 0 and (
            unserved >= 2 or features["first_service_wait_max"] >= config.epoch_ticks
            or features["ready_wait_p95"] >= config.epoch_ticks or features["recent_arrivals"] > 0)
        return ("MLFQ", "first_response_return") if urgent else (selected, None)
    if selected != "MLFQ" and not features["first_service_ready_count"]:
        # One observed quiet dwell establishes a lull; v6 adds another before
        # committing to an excursion that cannot immediately react to arrivals.
        quiet_window = config.epoch_ticks * config.dwell_epochs * config.arrival_quiet_dwell_periods
        if features["arrival_quiet_ticks"] < quiet_window:
            return active, "arrival_risk"
        if features["io_returns"] > 0 and features["ready_count"] > 1 and features["ready_wait_p95"] >= config.epoch_ticks:
            return active, "io_ready_pressure"
    return selected, None


def dynamic_policy_parameters(config: DynamicRouterConfig, priority_rr_config: dict) -> dict:
    registry = {**ALGORITHMS, **DEPLOYABLE_ALGORITHMS}
    parameters = {name: dict(registry[name][1]) for name in dynamic_policy_names(config)}
    parameters["Priority RR"] = dict(priority_rr_config)
    if "MLFQ" in parameters:
        parameters["MLFQ"] = {"quanta": config.mlfq_quanta, "aging_threshold": config.mlfq_aging_threshold}
    # Canonical JSON representation, including MLFQ's tuple-valued quanta.
    return json.loads(json.dumps(parameters))


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
    queue_level: int = 0
    quantum_used: int = 0
    aging_since: int | None = None

    def __post_init__(self):
        if self.aging_since is None:
            self.aging_since = self.time


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
    # The historical benefit experiment consumes these cumulative counters.
    arrivals_seen: int = 0
    total_io_returns: int = 0
    completed_burst_durations: list[int] = field(default_factory=list)
    burst_service: dict[str, int] = field(default_factory=dict)
    mlfq_quanta: tuple[int, ...] = (2, 4, 8)
    mlfq_aging_threshold: int = 20
    last_observed_arrival: int | None = None


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


def _new_state(processes: Iterable[Process], config: DynamicRouterConfig | None = None) -> _State:
    pending = sorted(copy.deepcopy(list(processes)), key=lambda process: (process.arrival_time, process.pid))
    if len({process.pid for process in pending}) != len(pending):
        raise ValueError("process IDs must be unique")
    for process in pending:
        process.reset()
    state = _State(pending, [], [], [], [])
    if config is not None:
        state.mlfq_quanta, state.mlfq_aging_threshold = config.mlfq_quanta, config.mlfq_aging_threshold
    return state


def _release(state: _State, until: int) -> None:
    events = []
    while state.pending and state.pending[0].arrival_time <= until:
        process = state.pending.pop(0)
        events.append((process.arrival_time, process.pid, process, process.priority, False))
        state.recent_arrivals += 1
        state.arrivals_seen += 1
        state.last_observed_arrival = process.arrival_time
    blocked = []
    for wake_time, process, priority, from_io in state.blocked:
        if wake_time <= until:
            events.append((wake_time, process.pid, process, priority, from_io))
            state.io_returns += int(from_io)
            state.total_io_returns += int(from_io)
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
        return (1 if item.priority <= 1 else max(1, item.priority - (now - item.time) // aging_interval), item.sequence)
    if policy == "SJF":
        return (item.process.burst_time, item.time, item.process.pid)
    if policy == "SRTF":
        return (item.process.remaining_time, item.time, item.process.pid)
    if policy == "Priority":
        return (item.process.priority, item.time, item.process.pid)
    return (item.time, item.process.pid)


def _rebuild_ready(state: _State, policy: str, priority_rr_config: dict) -> None:
    if policy == "MLFQ":
        _age_mlfq(state)
        state.ready.sort(key=lambda item: (item.queue_level, item.sequence))
        return
    state.ready.sort(key=lambda item: _ready_key(item, policy, state.current_time, priority_rr_config["aging_interval"]))


def _age_mlfq(state: _State) -> None:
    eligible = (item for item in state.ready if item.queue_level > 0
                and state.current_time - item.aging_since >= state.mlfq_aging_threshold)
    for item in sorted(eligible, key=lambda candidate: candidate.sequence):
        item.queue_level -= 1
        item.quantum_used = 0
        item.aging_since = state.current_time
        item.sequence = state.sequence
        state.sequence += 1


def _switch_policy(state: _State, previous: str, selected: str) -> None:
    # Enter MLFQ at its top queue; preserve CPU service and process/I/O state.
    if previous != selected and selected == "MLFQ":
        for item in state.ready:
            item.queue_level = item.quantum_used = 0


def _policy_config(priority_rr_config: dict | None) -> dict:
    return {**ALGORITHMS["Priority RR"][1], **(priority_rr_config or {})}


def _dispatch(
    state: _State, policy: str, priority_rr_config: dict,
    decision_times_ns: list[int] | None = None,
) -> None:
    _release(state, state.current_time)
    if not state.ready:
        times = [process.arrival_time for process in state.pending]
        times.extend(wake_time for wake_time, *_ in state.blocked)
        if not times:
            return
        state.current_time = min(times)
        _release(state, state.current_time)
    started = perf_counter_ns()
    _rebuild_ready(state, policy, priority_rr_config)
    ready = state.ready.pop(0)
    if decision_times_ns is not None:
        decision_times_ns.append(perf_counter_ns() - started)
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
    first_run = True
    while process.remaining_time:
        run_for = process.remaining_time
        if policy in {"Round Robin", "Priority RR"}:
            run_for = min(run_for, priority_rr_config["quantum"])
        elif policy == "MLFQ":
            run_for = min(run_for, state.mlfq_quanta[ready.queue_level] - ready.quantum_used)
            if ready.queue_level > 0:
                events = [state.pending[0].arrival_time] if state.pending else []
                events.extend(wake for wake, *_ in state.blocked)
                events.extend(item.aging_since + state.mlfq_aging_threshold for item in state.ready if item.queue_level > 0)
                if events:
                    run_for = min(run_for, max(0, min(events) - state.current_time))
        elif policy == "SRTF":
            next_events = [state.pending[0].arrival_time] if state.pending else []
            next_events.extend(wake_time for wake_time, *_ in state.blocked)
            if next_events:
                run_for = min(run_for, min(next_events) - state.current_time)
        end_time = state.current_time + run_for
        if (policy == "SRTF" or (policy == "MLFQ" and not first_run)) and state.timeline and state.timeline[-1][0] == process.pid and state.timeline[-1][2] == state.current_time:
            state.timeline[-1] = (process.pid, state.timeline[-1][1], end_time)
        else:
            state.timeline.append((process.pid, state.current_time, end_time))
        process.remaining_time -= run_for
        state.burst_service[process.pid] = state.burst_service.get(process.pid, 0) + run_for
        state.current_time = end_time
        if policy == "MLFQ":
            ready.quantum_used += run_for
        state.last_pid = process.pid
        _release(state, state.current_time)
        first_run = False
        if policy == "MLFQ":
            if not process.remaining_time or ready.quantum_used >= state.mlfq_quanta[ready.queue_level]:
                break
            _age_mlfq(state)
            if any(item.queue_level < ready.queue_level for item in state.ready):
                break
            continue
        if policy != "SRTF" or not process.remaining_time:
            break
        started = perf_counter_ns()
        should_preempt = any(item.process.remaining_time < process.remaining_time for item in state.ready)
        if decision_times_ns is not None:
            decision_times_ns.append(perf_counter_ns() - started)
        if should_preempt:
            break
    if process.remaining_time:
        level, used = 0, 0
        if policy == "MLFQ":
            level, used = ready.queue_level, ready.quantum_used
            if used >= state.mlfq_quanta[level]:
                level, used = min(level + 1, 2), 0
        state.ready.append(_Ready(state.current_time, state.sequence, process, process.priority, False, level, used))
        state.sequence += 1
    else:
        state.completed_burst_durations.append(state.burst_service.pop(process.pid))
    if not process.remaining_time and process.burst_index < len(process.cpu_bursts) - 1:
        wake_time = state.current_time + process.io_bursts[process.burst_index]
        process.burst_index += 1
        process.remaining_time = process.cpu_bursts[process.burst_index]
        state.blocked.append((wake_time, process, max(1, process.priority - 1), True))
    elif not process.remaining_time:
        process.completion_time = state.current_time
        state.completed.append(process)


def _run_to_completion(
    state: _State, policy: str, priority_rr_config: dict,
    decision_times_ns: list[int] | None = None,
) -> None:
    while state.pending or state.ready or state.blocked:
        _dispatch(state, policy, priority_rr_config, decision_times_ns)


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


def extract_dynamic_features(
    state: _State, active_policy: str = "Round Robin", dwell_remaining_ticks: int = 0,
) -> dict[str, float]:
    """Read only execution history and currently observed queues, in simulator ticks."""
    candidates = [item.process for item in state.ready] + [process for _, process, _, _ in state.blocked]
    priorities = [process.priority for process in candidates]
    waits = [max(0, state.current_time - item.time) for item in state.ready]
    service: dict[str, int] = {}
    for pid, start, end in state.timeline:
        if pid != "CS":
            service[pid] = service.get(pid, 0) + end - start
    durations = state.completed_burst_durations
    first_waits = [max(0, state.current_time - item.time) for item in state.ready if item.process.pid not in service]
    return {
        "ready_count": float(len(state.ready)), "blocked_count": float(len(state.blocked)),
        "completed_burst_mean": mean(durations) if durations else 0.0,
        "completed_burst_variance": pvariance(durations) if durations else 0.0,
        "observed_service_mean": mean(service.values()) if service else 0.0,
        "observed_service_variance": pvariance(service.values()) if service else 0.0,
        "priority_mean": mean(priorities) if priorities else 0.0,
        "ready_wait_mean": mean(waits) if waits else 0.0,
        "ready_wait_max": float(max(waits, default=0)),
        "recent_arrivals": float(state.recent_arrivals),
        "io_returns": float(state.io_returns),
        "io_return_ratio": state.io_returns / max(1, state.recent_arrivals + state.io_returns),
        "active_policy_index": float(tuple(dict.fromkeys((*DYNAMIC_POLICY_NAMES, *ALGORITHMS))).index(active_policy)),
        "dwell_remaining_ticks": float(max(0, dwell_remaining_ticks)),
        "first_service_ready_count": float(len(first_waits)),
        "first_service_wait_max": float(max(first_waits, default=0)),
        "ready_wait_p50": _percentile(waits, .5), "ready_wait_p95": _percentile(waits, .95),
        "arrival_quiet_ticks": float(max(0, state.current_time - state.last_observed_arrival))
                               if state.last_observed_arrival is not None else 0.,
    }


def _prediction(model, features: dict[str, float], policies=DYNAMIC_POLICY_NAMES) -> tuple[str, float]:
    row = [[features[name] for name in DYNAMIC_FEATURE_NAMES]]
    selected = str(model.predict(row)[0])
    if selected not in policies:
        raise ValueError(f"model selected ineligible policy for this track: {selected}")
    if hasattr(model, "predict_proba") and hasattr(model, "classes_"):
        probabilities = model.predict_proba(row)[0]
        confidence = float(max(probabilities))
    else:
        # Deterministic selectors have no classifier probability. Cost-model
        # decisions are guarded separately by their predicted improvement margin.
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
    policies = dynamic_policy_names(config)
    if hasattr(model, "dynamic_config_") and model.dynamic_config_ != config.__dict__:
        raise ValueError("runtime dynamic configuration differs from trained model; retrain")
    if hasattr(model, "policy_set_") and tuple(model.policy_set_) != policies:
        raise ValueError("runtime policy set differs from trained model; retrain")
    state = _new_state(processes, config)
    rr_config = _policy_config(priority_rr_config)
    if config.policy_track == "realistic" and rr_config != ALGORITHMS["Priority RR"][1]:
        raise ValueError("realistic routing requires the frozen Priority RR parameters")
    if hasattr(model, "priority_rr_config_") and model.priority_rr_config_ != rr_config:
        raise ValueError("runtime Priority RR configuration differs from trained model; retrain")
    active = config.initial_policy
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
            features = extract_dynamic_features(
                state, active, last_switch + config.dwell_epochs * config.epoch_ticks - state.current_time,
            )
            if model is None:
                if config.fallback_policy is None:
                    raise ValueError("an unavailable model requires an explicit fallback policy")
                selected, confidence = config.fallback_policy, 0.0
            else:
                selected, confidence = _prediction(model, features, dynamic_action_names(config))
                selected = _resolve_action(selected, active)
            fallback = config.fallback_policy is not None and (model is None or confidence < config.confidence_threshold)
            if fallback:
                selected = config.fallback_policy
            selected, safety_reason = _tail_action(features, active, selected, config)
            safety_return = safety_reason in {"excursion_expired", "first_response_return"}
            # Cost regressors use an absolute predicted advantage over the active
            # policy. This is a margin safeguard, not a calibrated probability.
            margin_ok = not hasattr(model, "switch_allowed") or model.switch_allowed(features, active, selected)
            dwell_elapsed = state.current_time - last_switch >= config.dwell_epochs * config.epoch_ticks
            protected = _protected(features, active, selected, config)
            accepted = selected != active and dwell_elapsed and not protected and (safety_return or fallback or (confidence >= config.confidence_threshold and margin_ok))
            reason = (
                "response_dwell_blocked" if safety_return and not dwell_elapsed else
                safety_reason if safety_reason is not None else
                "first_service_protection" if protected else "fallback_accepted" if accepted and fallback else
                "accepted" if accepted else "same_policy" if selected == active else
                "dwell_blocked" if fallback and not dwell_elapsed else
                "low_confidence" if confidence < config.confidence_threshold else
                "dwell_blocked" if not dwell_elapsed else "cost_margin"
            )
            if accepted:
                _switch_policy(state, active, selected)
                active = selected
                last_switch = state.current_time
                _rebuild_ready(state, active, rr_config)
            decisions.append(RoutingDecision(
                state.current_time, selected, active, confidence, accepted, reason, features,
                (perf_counter_ns() - started) / 1_000_000,
            ))
            state.recent_arrivals = state.io_returns = 0
        _dispatch(state, active, rr_config)
    return DynamicResult(_simulation(state, "Dynamic Adaptive"), config.initial_policy, active, decisions,
                         _percentile([decision.transition_ms for decision in decisions], 0.99))


def _counterfactual_label(
    state: _State, epoch_ticks: int, priority_rr_config: dict,
    policies=DYNAMIC_POLICY_NAMES, active_policy="Round Robin", dwell_remaining_ticks=0,
    *, config: DynamicRouterConfig | None = None, references=None,
) -> tuple[str, dict[str, float]]:
    """Feasible action then baseline continuation, on one fixed metric scale."""
    if dwell_remaining_ticks > 0:
        raise ValueError("dwell-blocked states cannot supply actionable labels")
    config = config or DynamicRouterConfig(epoch_ticks=epoch_ticks)
    results = {}
    expiry = state.current_time + config.effective_label_horizon
    boundary = ((expiry + config.epoch_ticks - 1) // config.epoch_ticks) * config.epoch_ticks
    continuation = config.label_continuation
    features = extract_dynamic_features(state, active_policy)
    for action in dict.fromkeys((*policies, continuation)):
        policy = _resolve_action(action, active_policy)
        policy, _ = _tail_action(features, active_policy, policy, config)
        if _protected(features, active_policy, policy, config):
            policy = active_policy
        trial = copy.deepcopy(state)
        _switch_policy(trial, active_policy, policy)
        while (trial.pending or trial.ready or trial.blocked) and trial.current_time < boundary:
            # Runtime reviews after an idle jump and before the next dispatch.
            # Do not let _dispatch cross the review and run a late job first.
            _release(trial, trial.current_time)
            if not trial.ready:
                events = [process.arrival_time for process in trial.pending]
                events.extend(wake for wake, *_ in trial.blocked)
                trial.current_time = min(events)
                _release(trial, trial.current_time)
                if trial.current_time >= boundary:
                    break
            _dispatch(trial, policy, priority_rr_config)
        _switch_policy(trial, policy, continuation)
        _run_to_completion(trial, continuation, priority_rr_config)
        results[action] = _simulation(trial, action)
    if references is None:
        # Direct callers still get one fixed reference scale, never per-action
        # normalization. Dataset generation supplies full-workload static bounds.
        references = results
    baseline = score_result_against_reference(results[continuation], references)
    scores = {policy: score_result_against_reference(results[policy], references) - baseline for policy in policies}
    label = min(policies, key=lambda policy: (scores[policy], policies.index(policy)))
    if "No Switch" in scores and scores["No Switch"] <= scores[label] + 1e-12:
        label = "No Switch"
    elif active_policy in scores and scores[active_policy] <= scores[label] + 1e-12:
        label = active_policy
    return label, scores


def _training_states(
    processes: Iterable[Process], config: DynamicRouterConfig, priority_rr_config: dict,
    behavior_policy: str = "Round Robin", behavior_seed: int = 0, behavior_model=None,
    *, max_states: int | None = None,
) -> list[tuple[_State, str, int]]:
    if max_states is not None and max_states <= 0:
        raise ValueError("max_states must be positive")
    state, states, next_epoch = _new_state(processes, config), [], config.epoch_ticks
    active, last_switch = config.initial_policy, 0
    randomizer = random.Random(behavior_seed)
    sampler, states_seen = random.Random(behavior_seed ^ 0xA2E), 0
    policies = dynamic_policy_names(config)
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
            dwell = max(0, last_switch + config.dwell_epochs * config.epoch_ticks - state.current_time)
            features = extract_dynamic_features(state, active, dwell)
            if not dwell:
                states_seen += 1
                if max_states is None or len(states) < max_states:
                    states.append((copy.deepcopy(state), active, dwell))
                else:
                    slot = sampler.randrange(states_seen)
                    if slot < max_states:
                        states[slot] = (copy.deepcopy(state), active, dwell)
            if behavior_model is not None:
                selected, confidence = _prediction(behavior_model, features, dynamic_action_names(config))
                selected = _resolve_action(selected, active)
                margin_ok = not hasattr(behavior_model, "switch_allowed") or behavior_model.switch_allowed(features, active, selected)
                if confidence < config.confidence_threshold and config.fallback_policy is not None:
                    selected, allow = config.fallback_policy, True
                else:
                    allow = confidence >= config.confidence_threshold and margin_ok
            else:
                selected = randomizer.choice(policies) if behavior_policy == "explore" else behavior_policy
                allow = True
            selected, safety_reason = _tail_action(features, active, selected, config)
            if safety_reason in {"excursion_expired", "first_response_return"}:
                allow = True
            if not dwell and allow and selected != active and not _protected(features, active, selected, config):
                _switch_policy(state, active, selected)
                active, last_switch = selected, state.current_time
            state.recent_arrivals = state.io_returns = 0
        _dispatch(state, active, priority_rr_config)
    return states


def build_dynamic_dataset(
    traces: int = 100, seed: int = 42, config: DynamicRouterConfig = DynamicRouterConfig(),
    priority_rr_config: dict | None = None,
    behavior_model=None,
    trace_indexes: Iterable[int] | None = None,
    development: bool = False,
) -> list[dict]:
    if traces <= 0:
        raise ValueError("traces must be positive")
    rr_config = _policy_config(priority_rr_config)
    if config.policy_track == "realistic" and rr_config != ALGORITHMS["Priority RR"][1]:
        raise ValueError("realistic training requires the frozen Priority RR parameters")
    rows = []
    policies = dynamic_policy_names(config)
    behaviors = (*policies, "explore")
    for index in range(traces) if trace_indexes is None else trace_indexes:
        # Vary cohort density in development only. Frozen evaluation generation
        # retains its original process counts, offsets, and seed stream.
        density = (3, 6, 12, 18)[(index // len(behaviors)) % 4]
        if development:
            from autoscheduler.development_workloads import DEV_FAMILIES, generate_development_workload
            if development == "v4":
                from autoscheduler.development_workloads import generate_development_workload_v4 as generate_development_workload
            workload = generate_development_workload(
                seed * 1_000_000 + index,
                family=DEV_FAMILIES[(index // len(behaviors)) % len(DEV_FAMILIES)],
            )
        else:
            workload = generate_dynamic_workload(seed * 1_000_000 + index, process_count=density)
        behavior = behaviors[index % len(behaviors)]
        references = compare_algorithms(workload.processes, rr_config)
        for epoch, (state, active, dwell) in enumerate(_training_states(
            workload.processes, config, rr_config, behavior, workload.seed, behavior_model,
        )):
            label, scores = _counterfactual_label(state, config.epoch_ticks, rr_config, dynamic_action_names(config), active, dwell,
                                                 config=config, references=references)
            row = extract_dynamic_features(state, active, dwell)
            ordered = sorted(scores.values())
            row.update({
                "seed": workload.seed, "epoch": epoch, "profiles": "/".join(workload.phase_profiles), "label": label,
                "behavior_policy": "adaptive" if behavior_model is not None else behavior,
                "development_family": getattr(workload, "family", "historical_cohort_generator"),
                "label_margin": ordered[1] - ordered[0],
                "optimal_policy_count": sum(abs(cost - ordered[0]) <= 1e-12 for cost in scores.values()),
            })
            row.update({f"score_{name.lower().replace(' ', '_')}": score for name, score in scores.items()})
            rows.append(row)
    if not rows:
        raise ValueError("dynamic traces produced no decision epochs")
    return rows


def evaluate_dynamic(
    model, traces: int = 1_000, seed: int = 2026, config: DynamicRouterConfig = DynamicRouterConfig(),
    priority_rr_config: dict | None = None,
    frozen_static_baseline: str = "Round Robin",
) -> tuple[list[dict], dict]:
    if traces <= 0:
        raise ValueError("traces must be positive")
    from autoscheduler.fairness import aggregate_fairness

    policies = dynamic_policy_names(config)
    if frozen_static_baseline not in policies:
        raise ValueError("frozen static baseline must be an eligible policy")
    rows = []
    latencies = []
    rr_config = _policy_config(priority_rr_config)
    for index in range(traces):
        workload = generate_dynamic_workload(seed * 1_000_000 + index)
        static = compare_algorithms(workload.processes, rr_config, tuple(dict.fromkeys((*ALGORITHMS, *policies))))
        adaptive = run_dynamic(workload.processes, model, config, rr_config)
        # Keep the historical six static policies as fixed normalization bounds.
        # Oracle references define only the metric scale, never deployable actions.
        references = {name: static[name] for name in ALGORITHMS}
        scores = {name: score_result_against_reference(result, references)
                  for name, result in {**static, "Adaptive": adaptive.simulation}.items()}
        latencies.extend(decision.transition_ms for decision in adaptive.decisions)
        rr_response = _percentile([metric.response_time for metric in static["Round Robin"].process_metrics], 0.95)
        adaptive_response = _percentile([metric.response_time for metric in adaptive.simulation.process_metrics], 0.95)
        baseline_response = _percentile([metric.response_time for metric in static[frozen_static_baseline].process_metrics], 0.95)
        starvation = aggregate_fairness(adaptive.simulation.process_metrics)["starvation_count"]
        baseline_starvation = aggregate_fairness(static[frozen_static_baseline].process_metrics)["starvation_count"]
        row = {
            "seed": workload.seed, "profiles": "/".join(workload.phase_profiles),
            "p95_response_round_robin": rr_response, "p95_response_adaptive": adaptive_response,
            "p95_response_difference": adaptive_response - rr_response,
            "weighted_score_round_robin": scores["Round Robin"], "weighted_score_adaptive": scores["Adaptive"],
            "weighted_score_difference": scores["Adaptive"] - scores["Round Robin"],
            "weighted_score_baseline": scores[frozen_static_baseline],
            "baseline_score_difference": scores["Adaptive"] - scores[frozen_static_baseline],
            "p95_response_baseline": baseline_response,
            "baseline_p95_response_difference": adaptive_response - baseline_response,
            "scheduling_regret": scores["Adaptive"] - min(scores[policy] for policy in policies),
            "starvation_count": starvation,
            "baseline_starvation_count": baseline_starvation,
            "transition_p99_ms": adaptive.transition_p99_ms,
            "accepted_switches": sum(decision.accepted for decision in adaptive.decisions),
            "held_decisions": sum(not decision.accepted for decision in adaptive.decisions),
            "dwell_blocked_decisions": sum(decision.reason == "dwell_blocked" for decision in adaptive.decisions),
            "low_confidence_decisions": sum(decision.reason == "low_confidence" for decision in adaptive.decisions),
            "mean_confidence": None if hasattr(model, "switch_allowed") else mean([decision.confidence for decision in adaptive.decisions] or [0.0]),
        }
        row.update({f"score_{name.lower().replace(' ', '_')}": score for name, score in scores.items() if name != "Adaptive"})
        rows.append(row)
    p95_ci = paired_bootstrap_ci([row["p95_response_difference"] for row in rows])
    score_ci = paired_bootstrap_ci([row["weighted_score_difference"] for row in rows])
    summary = {
        "traces": traces, "seed": seed, "config": config.__dict__,
        "status": "SYNTHETIC_DEVELOPMENT_ONLY",
        "eligible_policies": list(policies),
        "oracle_only_references": [name for name in ALGORITHMS if name not in policies],
        "normalization": "frozen_six_static_policy_bounds",
        "frozen_static_baseline": frozen_static_baseline,
        "baseline_score_difference": paired_bootstrap_ci([row["baseline_score_difference"] for row in rows]),
        "baseline_p95_response_difference": paired_bootstrap_ci([row["baseline_p95_response_difference"] for row in rows]),
        "mean_weighted_score": mean(row["weighted_score_adaptive"] for row in rows),
        "mean_p95_response": mean(row["p95_response_adaptive"] for row in rows),
        "mean_scheduling_regret": mean(row["scheduling_regret"] for row in rows),
        "mean_starvation_count": mean(row["starvation_count"] for row in rows),
        "mean_baseline_starvation_count": mean(row["baseline_starvation_count"] for row in rows),
        "decision_p99_ms": _percentile(latencies, .99),
        "confidence_kind": "predicted_cost_margin" if hasattr(model, "switch_allowed") else "classifier_leaf_probability",
        "p95_response_difference": p95_ci, "weighted_score_difference": score_ci,
        "mean_transition_p99_ms": mean(row["transition_p99_ms"] for row in rows),
        "max_transition_p99_ms": max(row["transition_p99_ms"] for row in rows),
        "mean_accepted_switches": mean(row["accepted_switches"] for row in rows),
        "mean_held_decisions": mean(row["held_decisions"] for row in rows),
        "mean_dwell_blocked_decisions": mean(row["dwell_blocked_decisions"] for row in rows),
        "mean_low_confidence_decisions": mean(row["low_confidence_decisions"] for row in rows),
        "mean_confidence": None if hasattr(model, "switch_allowed") else mean(row["mean_confidence"] for row in rows),
        "mean_static_scores": {
            name: mean(row[f"score_{name.lower().replace(' ', '_')}"] for row in rows)
            for name in static
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
    summary["beats_frozen_static_baseline"] = (
        summary["baseline_score_difference"]["ci_high"] < 0
        and summary["baseline_p95_response_difference"]["ci_high"] <= 0
        and summary["mean_starvation_count"] <= summary["mean_baseline_starvation_count"]
        and summary["latency_gate"]
    )
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
    policy_track: str = "realistic", model_kind: str = "classifier",
    initial_policy: str = "Round Robin", fallback_policy: str | None = None,
) -> dict:
    """Tune only on development traces, then return a frozen router configuration."""
    from autoscheduler.model import load_model, train_model

    if traces <= 0:
        raise ValueError("traces must be positive")
    candidates = []
    state_rows = {}
    rr_config = _policy_config(priority_rr_config)
    with tempfile.TemporaryDirectory() as directory:
        for index, (epoch, dwell, confidence) in enumerate(
            (epoch, dwell, confidence)
            for epoch in (5, 10, 20)
            for dwell in (1, 2, 3)
            for confidence in (0.0, 0.6, 0.8)
        ):
            config = DynamicRouterConfig(epoch, dwell, confidence, policy_track, initial_policy, fallback_policy)
            if (epoch, dwell) not in state_rows:
                state_rows[epoch, dwell] = build_dynamic_dataset(traces, seed, config, rr_config)
            rows = state_rows[epoch, dwell]
            path = Path(directory) / f"candidate_{index}.joblib"
            train_model(rows, path, seed, rr_config, DYNAMIC_FEATURE_NAMES, {"dynamic_config": config.__dict__}, group_key="seed", model_kind=model_kind)
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
