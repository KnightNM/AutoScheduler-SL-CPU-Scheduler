import unittest

from scheduler.fcfs import fcfs
from scheduler.priority import priority_scheduling
from scheduler.priority_rr import priority_round_robin
from scheduler.round_robin import round_robin
from scheduler.sjf import sjf
from scheduler.srtf import srtf
from simulator.process import Process
from simulator.engine import simulate
from simulator.simulator import run_simulation


class SchedulerTests(unittest.TestCase):
    def test_sjf_uses_total_cpu_burst_and_never_preempts(self):
        processes = [
            Process("A", 0, 9, cpu_bursts=(2, 7), io_bursts=(10,)),
            Process("B", 0, 4),
            Process("C", 1, 1),
        ]
        _, timeline = sjf(processes)
        self.assertEqual(timeline[:2], [("B", 0, 4), ("C", 4, 5)])
        self.assertEqual(timeline[2], ("A", 5, 7))

    def test_srtf_preempts_on_shorter_arrival_but_not_equal_or_longer(self):
        processes = [
            Process("A", 0, 9), Process("B", 1, 8),
            Process("C", 2, 2), Process("D", 3, 10),
        ]
        result = run_simulation("SRTF", srtf, processes)
        self.assertEqual(result.timeline, [("A", 0, 2), ("C", 2, 4), ("A", 4, 11), ("B", 11, 19), ("D", 19, 29)])
        self.assertEqual(result.context_switches, 4)
        self.assertEqual(len(result.process_metrics), len(processes))

    def test_srtf_preempts_on_shorter_io_return(self):
        processes = [
            Process("A", 0, 3, cpu_bursts=(1, 2), io_bursts=(2,)),
            Process("B", 0, 8),
        ]
        result = run_simulation("SRTF", srtf, processes)
        self.assertEqual(result.timeline, [("A", 0, 1), ("B", 1, 3), ("A", 3, 5), ("B", 5, 11)])
        self.assertEqual(result.process_metrics[0].post_io_response_times, (0,))
        self.assertTrue(all(metric.waiting_time >= 0 for metric in result.process_metrics))

    def test_srtf_does_not_preempt_on_equal_io_return(self):
        processes = [
            Process("A", 0, 3, cpu_bursts=(1, 2), io_bursts=(2,)),
            Process("B", 0, 4),
        ]
        result = run_simulation("SRTF", srtf, processes)
        self.assertEqual(result.timeline, [("A", 0, 1), ("B", 1, 5), ("A", 5, 7)])
        self.assertEqual(result.process_metrics[-1].post_io_response_times, (2,))

    def test_srtf_context_switch_cost_is_charged_only_on_process_change(self):
        completed, timeline = simulate(
            [Process("A", 0, 6), Process("B", 1, 2)],
            "srtf", preemptive=True, context_switch_cost=1,
        )
        self.assertEqual(timeline, [("A", 0, 1), ("CS", 1, 2), ("B", 2, 4), ("CS", 4, 5), ("A", 5, 10)])
        self.assertEqual(len(completed), 2)

    def test_fcfs_preserves_phase_one_schedule(self):
        processes = [
            Process("P1", 0, 5, 2),
            Process("P2", 1, 3, 1),
            Process("P3", 2, 8, 3),
            Process("P4", 3, 2, 2),
        ]
        _, timeline = fcfs(processes)
        self.assertEqual(
            timeline,
            [("P1", 0, 5), ("P2", 5, 8), ("P3", 8, 16), ("P4", 16, 18)],
        )

    def test_algorithms_break_ties_by_arrival_then_pid(self):
        processes = [Process("P2", 0, 2, 1), Process("P1", 0, 2, 1)]
        for scheduler in (fcfs, sjf, priority_scheduling):
            _, timeline = scheduler(processes)
            self.assertEqual([entry[0] for entry in timeline], ["P1", "P2"])

    def test_round_robin_enqueues_arrivals_before_preempted_process(self):
        _, timeline = round_robin(
            [Process("P1", 0, 5), Process("P2", 1, 3)], quantum=2
        )
        self.assertEqual(
            timeline,
            [
                ("P1", 0, 2),
                ("P2", 2, 4),
                ("P1", 4, 6),
                ("P2", 6, 7),
                ("P1", 7, 8),
            ],
        )

    def test_priority_round_robin_ages_waiting_processes(self):
        _, timeline = priority_round_robin(
            [Process("P1", 0, 1, priority=5), Process("P2", 0, 6, priority=1)],
            quantum=1,
            aging_interval=1,
            context_switch_cost=0,
        )
        self.assertEqual([pid for pid, _, _ in timeline][:5], ["P2", "P2", "P2", "P2", "P1"])

    def test_priority_round_robin_boosts_io_returning_process(self):
        _, timeline = priority_round_robin(
            [
                Process("P1", 0, 2, priority=2, cpu_bursts=(1, 1), io_bursts=(1,)),
                Process("P2", 0, 3, priority=2),
            ],
            quantum=1,
            aging_interval=10,
            context_switch_cost=0,
        )
        self.assertEqual([pid for pid, _, _ in timeline][:3], ["P1", "P2", "P1"])

    def test_priority_round_robin_charges_switch_time_not_idle_time(self):
        result = run_simulation(
            "Priority RR",
            priority_round_robin,
            [Process("P1", 0, 2, priority=1), Process("P2", 0, 1, priority=1)],
            quantum=1,
            aging_interval=10,
            context_switch_cost=1,
        )
        self.assertEqual(result.context_switches, 2)
        self.assertEqual(result.context_switch_time, 2)
        self.assertEqual(result.makespan, 5)
        self.assertEqual(result.idle_time, 0)
        self.assertEqual(result.max_waiting_time, 3)
        self.assertEqual(result.cpu_utilization, 3 / 5)

    def test_cpu_io_bursts_block_and_resume(self):
        processes = [
            Process("P1", 0, 4, cpu_bursts=(2, 2), io_bursts=(3,)),
            Process("P2", 1, 3),
        ]
        result = run_simulation("FCFS", fcfs, processes)
        self.assertEqual(
            result.timeline,
            [("P1", 0, 2), ("P2", 2, 5), ("P1", 5, 7)],
        )
        self.assertEqual({m.pid: m.waiting_time for m in result.process_metrics}, {"P1": 0, "P2": 1})
        self.assertEqual(result.cpu_utilization, 1.0)
        self.assertEqual(result.throughput, 2 / 7)
        self.assertEqual(result.context_switches, 2)

    def test_idle_cpu_metrics(self):
        result = run_simulation("FCFS", fcfs, [Process("P1", 3, 2)])
        self.assertEqual(result.makespan, 5)
        self.assertEqual(result.idle_time, 3)
        self.assertEqual(result.cpu_utilization, 0.4)

    def test_empty_workload_returns_zero_metrics(self):
        result = run_simulation("FCFS", fcfs, [])
        self.assertEqual(result.process_metrics, [])
        self.assertEqual(result.makespan, 0)
        self.assertEqual(result.cpu_utilization, 0.0)
        self.assertEqual(result.throughput, 0.0)

    def test_invalid_inputs_are_rejected(self):
        with self.assertRaises(ValueError):
            Process("P1", -1, 2)
        with self.assertRaises(ValueError):
            Process("P1", 0, 0)
        with self.assertRaises(ValueError):
            Process("P1", 0, 3, cpu_bursts=(2, 2), io_bursts=(1,))
        with self.assertRaises(ValueError):
            round_robin([Process("P1", 0, 2)], quantum=0)


if __name__ == "__main__":
    unittest.main()
