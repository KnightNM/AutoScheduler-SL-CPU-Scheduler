"""Synthetic development controls; never used to change frozen evaluation traces."""

from dataclasses import dataclass
import random

from simulator.process import Process


DEV_FAMILIES = (
    "cohort_mix", "sustained_arrivals", "low_load", "long_io",
    "repeated_changes", "homogeneous_batch",
)


@dataclass
class DevelopmentWorkload:
    seed: int
    family: str
    processes: list[Process]
    phase_profiles: tuple[str, ...]


def generate_development_workload(seed: int, family: str | None = None,
                                  process_count: int | None = None) -> DevelopmentWorkload:
    rng = random.Random(seed)
    family = family or rng.choice(DEV_FAMILIES)
    if family not in DEV_FAMILIES:
        raise ValueError("unknown development workload family")
    count = process_count if process_count is not None else rng.choice((12, 24, 36))
    if count <= 0:
        raise ValueError("process_count must be positive")
    processes = []
    profiles = (family,)
    batch_burst = rng.randint(15, 30)
    arrival = 0
    for index in range(count):
        priority = rng.randint(1, 5)
        if family == "homogeneous_batch":
            arrival, cpu, io = 0, (batch_burst,), ()
        elif family == "low_load":
            arrival, cpu, io = index * 80, (rng.randint(1, 4),), ()
        elif family == "long_io":
            arrival = index % 4
            cpu = tuple(rng.randint(8, 20) for _ in range(3))
            io = tuple(rng.randint(50, 150) for _ in range(2))
        elif family == "sustained_arrivals":
            arrival = index * 6 + rng.randint(0, 2)
            cpu = (rng.randint(2, 12),) if index % 3 else (rng.randint(12, 24), rng.randint(1, 5))
            io = (rng.randint(5, 20),) if len(cpu) == 2 else ()
        else:
            phases = ("batch", "interactive", "cpu", "io", "batch") if family == "repeated_changes" else ("batch", "interactive", "io")
            phase = min(len(phases) - 1, index * len(phases) // count)
            profile = phases[phase]
            profiles = phases
            arrival = phase * (120 if family == "repeated_changes" else 20) + rng.randint(0, 3)
            if profile == "interactive":
                cpu, io = (1, rng.randint(1, 3), 1), (rng.randint(2, 8), rng.randint(2, 8))
            elif profile == "io":
                cpu, io = (2, 3, 2), (rng.randint(20, 60), rng.randint(20, 60))
            elif profile == "cpu":
                cpu, io = (rng.randint(30, 60),), ()
            else:
                cpu, io = (rng.randint(10, 30),), ()
        processes.append(Process(f"P{index + 1}", arrival, sum(cpu), priority, cpu, io))
    return DevelopmentWorkload(seed, family, processes, tuple(profiles))


def generate_development_workload_v4(seed: int, family: str | None = None,
                                     process_count: int | None = None) -> DevelopmentWorkload:
    """Balanced families, broader counts and unpredictable arrivals; no outcome filtering."""
    rng = random.Random(seed)
    family = family or rng.choice(DEV_FAMILIES)
    count = process_count if process_count is not None else rng.choice((3, 6, 12, 24, 48))
    workload = generate_development_workload(seed, family, count)
    arrival = 0
    for index, process in enumerate(workload.processes):
        if family == "sustained_arrivals":
            arrival += int(rng.expovariate(1 / 8)) if seed % 2 else rng.choice((0, 1, 3, 15, 30))
            process.arrival_time = arrival
        elif family == "long_io" and seed % 2 == 0:
            # A prespecified sparse, long-I/O control where FCFS can win.
            process.cpu_bursts, process.io_bursts = (20, 20, 20), (100, 100)
            process.burst_time, process.remaining_time = 60, 20
        elif family == "repeated_changes":
            phase = min(4, index * 5 // count)
            process.arrival_time += phase * (seed % 61)
    return workload
