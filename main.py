"""
main.py
-------
AutoScheduler: Self-Learning CPU Scheduling Algorithm
Phase 1 — Basic CPU Scheduling Engine Demo

Runs all four classic scheduling algorithms on an identical hardcoded
workload and prints the Gantt chart plus key performance metrics for each.
"""

from simulator.process   import Process
from simulator.simulator import run_simulation, SimulationResult
from scheduler.fcfs        import fcfs
from scheduler.sjf         import sjf
from scheduler.round_robin import round_robin
from scheduler.priority    import priority_scheduling
from scheduler.srtf        import srtf


# ---------------------------------------------------------------------------
# Hardcoded test workload
# ---------------------------------------------------------------------------
def make_processes():
    """Return a fresh list of processes for each algorithm run."""
    return [
        Process(pid="P1", arrival_time=0, burst_time=5, priority=2),
        Process(pid="P2", arrival_time=1, burst_time=3, priority=1),
        Process(pid="P3", arrival_time=2, burst_time=8, priority=3),
        Process(pid="P4", arrival_time=3, burst_time=2, priority=2),
    ]


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------
SEPARATOR = "=" * 60


def print_gantt(timeline):
    """
    Print a text Gantt chart.

    Example output:
        | P1 | P2 | P4 | P3 |
          0    5    8   10   18
    """
    # Top bar with process labels.
    bar = " | ".join(f"{pid:^4}" for pid, _, _ in timeline)
    print(f"  | {bar} |")

    # Time markers below.
    markers = ""
    prev_end = None
    for _, start, end in timeline:
        if prev_end is None:
            markers += f"  {start}"
        markers += f"{' ' * 4}{end}"
        prev_end = end
    print(markers)


def print_result(result: SimulationResult):
    """Print a formatted summary of one algorithm's simulation result."""
    print(SEPARATOR)
    print(f"  Algorithm : {result.algorithm}")
    print(SEPARATOR)

    # Gantt chart
    print("\n  Gantt Chart / Execution Timeline:")
    print()
    for entry in result.timeline:
        print(f"    {entry}")
    print()
    print_gantt(result.timeline)
    print()

    # Per-process table
    header = (
        f"  {'PID':<6} {'Arrival':>8} {'Burst':>7} "
        f"{'Start':>7} {'Finish':>8} {'TAT':>6} {'WT':>6} {'RT':>6}"
    )
    print(header)
    print("  " + "-" * (len(header) - 2))
    for m in sorted(result.process_metrics, key=lambda x: x.pid):
        print(
            f"  {m.pid:<6} {m.arrival_time:>8} {m.burst_time:>7} "
            f"{m.start_time:>7} {m.completion_time:>8} "
            f"{m.turnaround_time:>6} {m.waiting_time:>6} {m.response_time:>6}"
        )
    print()

    # Averages
    print(f"  Average Turnaround Time : {result.avg_turnaround_time:.2f}")
    print(f"  Average Waiting Time    : {result.avg_waiting_time:.2f}")
    print(f"  Average Response Time   : {result.avg_response_time:.2f}")
    print(f"  CPU Utilization         : {result.cpu_utilization:.2%}")
    print(f"  Throughput              : {result.throughput:.3f}")
    print(f"  Context Switches        : {result.context_switches}")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def demo():
    print()
    print("=" * 60)
    print("  AutoScheduler — CPU Scheduling Engine Demo")
    print("=" * 60)
    print()
    print("  Workload:")
    for p in make_processes():
        print(
            f"    {p.pid}: arrival={p.arrival_time}, "
            f"burst={p.burst_time}, priority={p.priority}"
        )
    print()

    runs = [
        ("FCFS",                        fcfs,               {}),
        ("SJF (non-preemptive)",        sjf,                {}),
        ("SRTF (preemptive SJF)",       srtf,               {}),
        ("Round Robin (q=2)",           round_robin,        {"quantum": 2}),
        ("Priority (non-preemptive)",   priority_scheduling, {}),
    ]

    for name, fn, kwargs in runs:
        result = run_simulation(name, fn, make_processes(), **kwargs)
        print_result(result)

    print(SEPARATOR)
    print("  Done.")
    print(SEPARATOR)


def main():
    import sys

    if len(sys.argv) == 1:
        demo()
        return
    from autoscheduler.cli import main as cli_main

    cli_main()


if __name__ == "__main__":
    main()
