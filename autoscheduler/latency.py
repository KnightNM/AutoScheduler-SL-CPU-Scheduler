"""Wall-clock scheduling-decision benchmark."""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from statistics import mean
from time import perf_counter_ns

from autoscheduler.adaptive import select_scheduler
from autoscheduler.evaluation import ALGORITHMS
from autoscheduler.features import extract_features
from autoscheduler.workloads import PROFILES, generate_workload
from simulator.engine import simulate


SIZES = {"small": 12, "medium": 100, "large": 1_000}
POLICIES = ("SJF", "SRTF", "Round Robin", "Priority", "Priority RR", "Adaptive")
_ENGINE_POLICIES = {"SJF": "sjf", "SRTF": "srtf", "Round Robin": "rr", "Priority": "priority", "Priority RR": "priority_rr"}


def percentile(values: list[float], fraction: float) -> float:
    """Return a linearly interpolated percentile for a non-empty sample."""
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low, high = int(position), min(int(position) + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _stats(samples: list[float]) -> dict[str, float | int]:
    return {
        "samples": len(samples), "mean_ms": mean(samples), "min_ms": min(samples), "max_ms": max(samples),
        "p50_ms": percentile(samples, 0.50), "p95_ms": percentile(samples, 0.95), "p99_ms": percentile(samples, 0.99),
    }


def select_recommended_policy(
    latency: dict,
    scores: dict[str, float],
    adaptive_statistically_beats_static: bool | None = None,
) -> dict:
    passing = {
        policy: all(latency[policy][size]["p99_ms"] < 10.0 for size in SIZES)
        for policy in latency
    }
    static = [policy for policy in POLICIES[:-1] if passing.get(policy) and policy in scores]
    best_static = min(static, key=scores.get) if static else None
    adaptive_beats_static = bool(
        passing.get("Adaptive") and best_static and scores["Adaptive"] < scores[best_static]
    )
    statistical_pass = (
        adaptive_beats_static
        if adaptive_statistically_beats_static is None
        else adaptive_beats_static and adaptive_statistically_beats_static
    )
    eligible_for_adaptive = bool(passing.get("Adaptive") and statistical_pass)
    recommended = "Adaptive" if eligible_for_adaptive else best_static
    if recommended is None:
        eligible = [policy for policy, passed in passing.items() if passed and policy in scores]
        recommended = min(eligible, key=scores.get) if eligible else None
    return {
        "gate_p99_ms": 10.0,
        "passes_latency_gate": passing,
        "best_static_policy": best_static,
        "adaptive_beats_static": adaptive_beats_static,
        "adaptive_statistically_beats_static": statistical_pass,
        "eligible_for_adaptive": eligible_for_adaptive,
        "recommended_policy": recommended,
    }


def run_latency_experiment(model, score_summary: dict, samples_per_profile: int = 20, seed: int = 3030, warmups: int = 5) -> tuple[list[dict], dict]:
    if samples_per_profile <= 0 or warmups < 0:
        raise ValueError("samples_per_profile must be positive and warmups must be non-negative")
    priority_rr_config = score_summary.get("priority_rr_config", ALGORITHMS["Priority RR"][1])
    measurements = {policy: {size: [] for size in SIZES} for policy in POLICIES}
    for size_index, (size, count) in enumerate(SIZES.items()):
        workloads = (
            (sample >= warmups, generate_workload(
                profile, seed * 10_000_000 + size_index * 1_000_000 + profile_index * 100_000 + sample, count
            ))
            for profile_index, profile in enumerate(PROFILES)
            for sample in range(samples_per_profile + warmups)
        )
        for measured, workload in workloads:
            for name, policy in _ENGINE_POLICIES.items():
                kwargs = ALGORITHMS[name][1]
                if name == "Priority RR":
                    kwargs = {**kwargs, **priority_rr_config}
                decision_times_ns: list[int] = []
                simulate(workload.processes, policy, decision_times_ns=decision_times_ns, preemptive=policy == "srtf", **kwargs)
                if measured:
                    samples = [value / 1_000_000 for value in decision_times_ns]
                    measurements[name][size].extend(samples)
            started = perf_counter_ns()
            select_scheduler(extract_features(workload.processes), model)
            if measured:
                latency_ms = (perf_counter_ns() - started) / 1_000_000
                measurements["Adaptive"][size].append(latency_ms)
    latency = {policy: {size: _stats(samples) for size, samples in sizes.items()} for policy, sizes in measurements.items()}
    rows = [
        {"policy": policy, "size": size, **stats, "passes_gate": stats["p99_ms"] < 10.0}
        for policy, sizes in latency.items()
        for size, stats in sizes.items()
    ]
    scores = {name: values["mean_score"] for name, values in score_summary["static_policies"].items() if name in POLICIES}
    scores["Adaptive"] = score_summary["mean_adaptive_score"]
    selection = select_recommended_policy(
        latency,
        scores,
        score_summary.get("adaptive_statistically_beats_static"),
    )
    return rows, {"seed": seed, "samples_per_profile": samples_per_profile, "warmups": warmups, "sizes": SIZES, "scores": scores, "latency": latency, **selection}


def save_latency(rows: list[dict], summary: dict, output_dir: str | Path) -> None:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "latency.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)
    (output_dir / "latency_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    cache_dir = Path(".cache/matplotlib").resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ["MPLCONFIGDIR"], os.environ["XDG_CACHE_HOME"] = str(cache_dir), str(cache_dir)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    figure, axis = plt.subplots(figsize=(9, 4))
    sizes = list(SIZES)
    for policy in POLICIES:
        axis.plot(sizes, [summary["latency"][policy][size]["p99_ms"] for size in sizes], marker="o", label=policy)
    axis.axhline(10.0, color="red", linestyle="--", label="10 ms gate")
    axis.set_ylabel("P99 decision latency (ms)")
    axis.legend(fontsize="small")
    figure.tight_layout()
    figure.savefig(output_dir / "latency.png")
    plt.close(figure)
