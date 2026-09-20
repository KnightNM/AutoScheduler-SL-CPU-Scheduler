"""
tests/test_srtf.py
------------------
Unit tests for the SRTF (Shortest Remaining Time First) scheduler.

Each test documents the expected timeline manually so that any regression
in scheduling logic is immediately visible.

Conventions used in this file
------------------------------
- Processes are constructed fresh for every test to avoid mutation side-
  effects across tests.
- Timeline entries are (pid, start, end) triples produced by srtf().
- Metrics are verified via run_simulation() using the same SimulationResult
  interface as every other algorithm.
"""

import unittest

from scheduler.fcfs        import fcfs
from scheduler.sjf         import sjf
from scheduler.round_robin import round_robin
from scheduler.priority    import priority_scheduling
from scheduler.srtf        import srtf
from simulator.process     import Process
from simulator.simulator   import run_simulation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pids(timeline):
    """Return just the pid sequence from a timeline."""
    return [pid for pid, _, _ in timeline]


def _metrics(timeline_or_result, *, pid):
    """Extract per-process metrics by pid from a SimulationResult."""
    result = timeline_or_result
    return next(m for m in result.process_metrics if m.pid == pid)


# ---------------------------------------------------------------------------
# Core preemption behaviour
# ---------------------------------------------------------------------------

class TestSrtfPreemption(unittest.TestCase):

    def test_shorter_arrival_preempts_longer_job(self):
        """
        Classic SRTF preemption example:
          P1: arrival=0, burst=8
          P2: arrival=2, burst=3

        Expected execution:
          t 0-2  : P1 runs (remaining_time goes from 8 to 6)
          t 2-5  : P2 arrives and has remaining=3 < 6, preempts P1; P2 runs to completion
          t 5-11 : P1 resumes with remaining_time=6 and runs to completion

        Timeline: [(P1,0,2), (P2,2,5), (P1,5,11)]
        """
        processes = [
            Process(pid="P1", arrival_time=0, burst_time=8),
            Process(pid="P2", arrival_time=2, burst_time=3),
        ]
        scheduled, timeline = srtf(processes)

        self.assertEqual(
            timeline,
            [("P1", 0, 2), ("P2", 2, 5), ("P1", 5, 11)],
        )
        self.assertEqual({p.pid for p in scheduled}, {"P1", "P2"})

    def test_no_preemption_when_running_job_is_shorter(self):
        """
        If the running job is always shorter than any new arrival, SRTF
        should not preempt.

        P1: arrival=0, burst=3
        P2: arrival=1, burst=5

        Expected:
          t 0-3  : P1 runs (burst=3 < remaining burst of 5 for P2)
          t 3-8  : P2 runs

        Timeline: [(P1,0,3), (P2,3,8)]
        """
        processes = [
            Process(pid="P1", arrival_time=0, burst_time=3),
            Process(pid="P2", arrival_time=1, burst_time=5),
        ]
        _, timeline = srtf(processes)

        self.assertEqual(timeline, [("P1", 0, 3), ("P2", 3, 8)])

    def test_srtf_differs_from_nonpreemptive_sjf(self):
        """
        Verify that SRTF and non-preemptive SJF produce different timelines
        for a workload where preemption changes the order.

        P1: arrival=0, burst=8
        P2: arrival=2, burst=3

        SJF  (non-preemptive): P1 runs 0-8, P2 runs 8-11.
        SRTF (preemptive):     P1 runs 0-2, P2 runs 2-5, P1 runs 5-11.
        """
        processes = [
            Process(pid="P1", arrival_time=0, burst_time=8),
            Process(pid="P2", arrival_time=2, burst_time=3),
        ]
        _, sjf_tl  = sjf(processes)
        _, srtf_tl = srtf(processes)

        self.assertNotEqual(sjf_tl, srtf_tl)

        # SJF: P1 runs without interruption
        self.assertEqual(sjf_tl[0], ("P1", 0, 8))
        # SRTF: P1 is preempted at t=2
        self.assertEqual(srtf_tl[0], ("P1", 0, 2))
        self.assertEqual(srtf_tl[1], ("P2", 2, 5))

    def test_multiple_preemptions(self):
        """
        Three processes where preemptions happen at every arrival.

        P1: arrival=0, burst=10
        P2: arrival=1, burst=4
        P3: arrival=2, burst=2

        t 0-1  : P1 runs (remaining=9)
        t 1-2  : P2 arrives (remaining=4 < 9), preempts P1; P2 runs (remaining=3)
        t 2-4  : P3 arrives (remaining=2 < 3), preempts P2; P3 runs to completion
        t 4-7  : P2 resumes (remaining=3), runs to completion
        t 7-16 : P1 resumes (remaining=9), runs to completion
        """
        processes = [
            Process(pid="P1", arrival_time=0, burst_time=10),
            Process(pid="P2", arrival_time=1, burst_time=4),
            Process(pid="P3", arrival_time=2, burst_time=2),
        ]
        _, timeline = srtf(processes)

        self.assertEqual(
            timeline,
            [
                ("P1", 0, 1),
                ("P2", 1, 2),
                ("P3", 2, 4),
                ("P2", 4, 7),
                ("P1", 7, 16),
            ],
        )


# ---------------------------------------------------------------------------
# Tie-breaking
# ---------------------------------------------------------------------------

class TestSrtfTieBreaking(unittest.TestCase):

    def test_equal_remaining_time_prefers_earlier_arrival(self):
        """
        P1: arrival=0, burst=5
        P2: arrival=0, burst=5

        Both have the same remaining_time and burst_time. Tie is broken by
        arrival_time (equal here) then by pid lexicographically: P1 < P2,
        so P1 should run first.
        """
        processes = [
            Process(pid="P1", arrival_time=0, burst_time=5),
            Process(pid="P2", arrival_time=0, burst_time=5),
        ]
        _, timeline = srtf(processes)

        self.assertEqual(_pids(timeline), ["P1", "P2"])

    def test_equal_remaining_time_mid_run_prefers_running_process(self):
        """
        When a new process arrives with the same remaining_time as the
        currently running process, the running process should NOT be
        preempted (it has the lower pid and same burst, and the running
        process has already started).

        P1: arrival=0, burst=5  → currently running with remaining=5
        P2: arrival=0, burst=5  → has remaining=5 (equal)

        Expected: P1 runs without interruption, then P2.
        """
        processes = [
            Process(pid="P1", arrival_time=0, burst_time=5),
            Process(pid="P2", arrival_time=0, burst_time=5),
        ]
        _, timeline = srtf(processes)

        # P1 must be a single uninterrupted segment
        self.assertEqual(timeline[0], ("P1", 0, 5))
        self.assertEqual(timeline[1], ("P2", 5, 10))

    def test_new_arrival_tie_with_remaining_does_not_preempt(self):
        """
        P1: arrival=0, burst=5   (running, remaining=3 at t=2)
        P2: arrival=2, burst=3   (arrives with remaining=3, same as P1)

        P1 arrived earlier so it should not be preempted when P2 ties.
        Expected: P1 runs 0-5, P2 runs 5-8.
        """
        processes = [
            Process(pid="P1", arrival_time=0, burst_time=5),
            Process(pid="P2", arrival_time=2, burst_time=3),
        ]
        _, timeline = srtf(processes)

        self.assertEqual(timeline[0], ("P1", 0, 5))
        self.assertEqual(timeline[1], ("P2", 5, 8))


# ---------------------------------------------------------------------------
# Idle CPU
# ---------------------------------------------------------------------------

class TestSrtfIdleCpu(unittest.TestCase):

    def test_single_process_arriving_late(self):
        """
        Only one process, arriving at t=5.

        Expected:
          CPU idle 0-5.
          P1 runs 5-10.
          Timeline: [(P1, 5, 10)]
        """
        processes = [Process(pid="P1", arrival_time=5, burst_time=5)]
        _, timeline = srtf(processes)

        self.assertEqual(timeline, [("P1", 5, 10)])

    def test_gap_between_two_processes(self):
        """
        P1: arrival=0, burst=3 → completes at t=3
        P2: arrival=6, burst=2 → CPU idle 3-6, then P2 runs 6-8

        Timeline: [(P1, 0, 3), (P2, 6, 8)]
        """
        processes = [
            Process(pid="P1", arrival_time=0, burst_time=3),
            Process(pid="P2", arrival_time=6, burst_time=2),
        ]
        _, timeline = srtf(processes)

        self.assertEqual(timeline, [("P1", 0, 3), ("P2", 6, 8)])

    def test_empty_workload(self):
        """An empty process list should return two empty lists."""
        scheduled, timeline = srtf([])
        self.assertEqual(scheduled, [])
        self.assertEqual(timeline, [])

    def test_single_process_no_preemption(self):
        """Single process should run uninterrupted."""
        processes = [Process(pid="P1", arrival_time=0, burst_time=7)]
        _, timeline = srtf(processes)
        self.assertEqual(timeline, [("P1", 0, 7)])


# ---------------------------------------------------------------------------
# Metric correctness
# ---------------------------------------------------------------------------

class TestSrtfMetrics(unittest.TestCase):

    def test_completion_turnaround_waiting_response_times(self):
        """
        P1: arrival=0, burst=8
        P2: arrival=2, burst=3

        Expected schedule: P1[0-2], P2[2-5], P1[5-11]

        P2: CT=5,  TAT=5-2=3,  WT=3-3=0,  RT=2-2=0
        P1: CT=11, TAT=11-0=11, WT=11-8=3, RT=0-0=0
        """
        processes = [
            Process(pid="P1", arrival_time=0, burst_time=8),
            Process(pid="P2", arrival_time=2, burst_time=3),
        ]
        result = run_simulation("SRTF", srtf, processes)

        m1 = _metrics(result, pid="P1")
        m2 = _metrics(result, pid="P2")

        self.assertEqual(m1.completion_time, 11)
        self.assertEqual(m1.turnaround_time, 11)
        self.assertEqual(m1.waiting_time, 3)
        self.assertEqual(m1.response_time, 0)

        self.assertEqual(m2.completion_time, 5)
        self.assertEqual(m2.turnaround_time, 3)
        self.assertEqual(m2.waiting_time, 0)
        self.assertEqual(m2.response_time, 0)

    def test_average_waiting_time(self):
        """
        P1: arrival=0, burst=8 → WT=3
        P2: arrival=2, burst=3 → WT=0
        avg WT = (3 + 0) / 2 = 1.5
        """
        processes = [
            Process(pid="P1", arrival_time=0, burst_time=8),
            Process(pid="P2", arrival_time=2, burst_time=3),
        ]
        result = run_simulation("SRTF", srtf, processes)
        self.assertAlmostEqual(result.avg_waiting_time, 1.5)

    def test_response_time_first_cpu_access(self):
        """
        P1 arrives at t=0 and immediately gets CPU → RT = 0.
        P2 arrives at t=2 and immediately preempts → RT = 0.
        """
        processes = [
            Process(pid="P1", arrival_time=0, burst_time=8),
            Process(pid="P2", arrival_time=2, burst_time=3),
        ]
        result = run_simulation("SRTF", srtf, processes)
        for m in result.process_metrics:
            self.assertEqual(m.response_time, 0, msg=f"{m.pid} response_time should be 0")

    def test_completion_times_correct_for_multiple_preemptions(self):
        """
        P1: arrival=0, burst=10   CT=16
        P2: arrival=1, burst=4    CT=7
        P3: arrival=2, burst=2    CT=4

        Schedule: P1[0-1], P2[1-2], P3[2-4], P2[4-7], P1[7-16]
        """
        processes = [
            Process(pid="P1", arrival_time=0, burst_time=10),
            Process(pid="P2", arrival_time=1, burst_time=4),
            Process(pid="P3", arrival_time=2, burst_time=2),
        ]
        result = run_simulation("SRTF", srtf, processes)

        m1 = _metrics(result, pid="P1")
        m2 = _metrics(result, pid="P2")
        m3 = _metrics(result, pid="P3")

        self.assertEqual(m1.completion_time, 16)
        self.assertEqual(m2.completion_time, 7)
        self.assertEqual(m3.completion_time, 4)

        # TAT = CT - arrival
        self.assertEqual(m1.turnaround_time, 16)  # 16 - 0
        self.assertEqual(m2.turnaround_time, 6)   # 7  - 1
        self.assertEqual(m3.turnaround_time, 2)   # 4  - 2

        # WT = TAT - burst
        self.assertEqual(m1.waiting_time, 6)   # 16 - 10
        self.assertEqual(m2.waiting_time, 2)   # 6  - 4
        self.assertEqual(m3.waiting_time, 0)   # 2  - 2

    def test_all_processes_scheduled_exactly_once(self):
        """Every input process must appear exactly once in the scheduled list."""
        processes = [
            Process(pid="P1", arrival_time=0, burst_time=6),
            Process(pid="P2", arrival_time=2, burst_time=3),
            Process(pid="P3", arrival_time=4, burst_time=1),
        ]
        scheduled, _ = srtf(processes)
        pids = [p.pid for p in scheduled]
        self.assertEqual(sorted(pids), ["P1", "P2", "P3"])

    def test_originals_not_mutated(self):
        """srtf() must not modify the caller's process objects."""
        processes = [
            Process(pid="P1", arrival_time=0, burst_time=8),
            Process(pid="P2", arrival_time=2, burst_time=3),
        ]
        original_bt = {p.pid: p.burst_time for p in processes}
        original_rt = {p.pid: p.remaining_time for p in processes}

        srtf(processes)

        for p in processes:
            self.assertEqual(p.burst_time, original_bt[p.pid])
            self.assertEqual(p.remaining_time, original_rt[p.pid])
            self.assertEqual(p.start_time, -1)
            self.assertEqual(p.completion_time, -1)


# ---------------------------------------------------------------------------
# Regression: existing schedulers must pass unchanged
# ---------------------------------------------------------------------------

class TestExistingSchedulersUnaffected(unittest.TestCase):
    """
    Smoke-test the existing algorithms to confirm the SRTF addition has not
    altered their behaviour.  These mirror the Phase-1 demo workload.
    """

    def setUp(self):
        self.workload = [
            Process(pid="P1", arrival_time=0, burst_time=5, priority=2),
            Process(pid="P2", arrival_time=1, burst_time=3, priority=1),
            Process(pid="P3", arrival_time=2, burst_time=8, priority=3),
            Process(pid="P4", arrival_time=3, burst_time=2, priority=2),
        ]

    def test_fcfs_unchanged(self):
        _, timeline = fcfs(self.workload)
        self.assertEqual(
            timeline,
            [("P1", 0, 5), ("P2", 5, 8), ("P3", 8, 16), ("P4", 16, 18)],
        )

    def test_sjf_unchanged(self):
        from scheduler.sjf import sjf
        _, timeline = sjf(self.workload)
        # SJF picks smallest burst from those available at each decision.
        # At t=0: only P1 available (burst=5). Runs to t=5.
        # At t=5: P2(3), P3(8), P4(2) — picks P4(2). Runs to t=7.
        # At t=7: P2(3), P3(8) — picks P2(3). Runs to t=10.
        # At t=10: P3(8). Runs to t=18.
        self.assertEqual(timeline[0], ("P1", 0, 5))
        self.assertEqual(timeline[1], ("P4", 5, 7))
        self.assertEqual(timeline[2], ("P2", 7, 10))
        self.assertEqual(timeline[3], ("P3", 10, 18))

    def test_round_robin_unchanged(self):
        _, timeline = round_robin(self.workload, quantum=2)
        self.assertEqual(
            timeline,
            [
                ("P1", 0, 2),
                ("P2", 2, 4),
                ("P3", 4, 6),
                ("P1", 6, 8),
                ("P4", 8, 10),
                ("P2", 10, 11),
                ("P3", 11, 13),
                ("P1", 13, 14),
                ("P3", 14, 16),
                ("P3", 16, 18),
            ],
        )

    def test_priority_unchanged(self):
        _, timeline = priority_scheduling(self.workload)
        self.assertEqual(
            timeline,
            [("P1", 0, 5), ("P2", 5, 8), ("P4", 8, 10), ("P3", 10, 18)],
        )

    def test_srtf_differs_from_sjf_on_demo_workload(self):
        """SRTF must produce a different timeline than SJF for this workload."""
        _, sjf_tl = sjf(self.workload)
        _, srtf_tl = srtf(self.workload)
        # In SRTF, P2 (burst=3) arrives at t=1 and preempts P1 (remaining=4 > 3).
        self.assertNotEqual(sjf_tl, srtf_tl)
        # The first preemption happens at t=1.
        self.assertEqual(srtf_tl[0], ("P1", 0, 1))
        self.assertEqual(srtf_tl[1], ("P2", 1, 4))


if __name__ == "__main__":
    unittest.main()
