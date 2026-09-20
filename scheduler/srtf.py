"""Shortest Remaining Time First (preemptive, current CPU burst)."""

from typing import List, Tuple

from simulator.engine import simulate
from simulator.process import Process


def srtf(processes: List[Process]) -> Tuple[List[Process], List[Tuple[str, int, int]]]:
    """Run preemptive SRTF; arrivals and I/O completions can interrupt a burst."""
    return simulate(processes, "srtf", preemptive=True)
