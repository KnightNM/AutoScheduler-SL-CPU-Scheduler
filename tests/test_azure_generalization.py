"""Tiny, data-free checks for external-evaluation descriptors and grouping."""
import unittest

from autoscheduler.azure_generalization import characteristics
from autoscheduler.azure_generalization_evaluation import provenance_groups


class AzureGeneralizationTests(unittest.TestCase):
    def test_nonpreemptive_excursion_cannot_enforce_a_twenty_tick_return(self):
        # Diagnostic contract: a dwell horizon is not a preemption timer. Keep
        # this limitation visible rather than silently changing policy semantics.
        from autoscheduler.dynamic import DynamicRouterConfig, run_dynamic
        from scheduler.mlfq import mlfq
        from simulator.process import Process
        from simulator.simulator import run_simulation
        class PriorityProposal:
            def predict(self, matrix):
                return ['Priority'] * len(matrix)
        config = DynamicRouterConfig(epoch_ticks=10, dwell_epochs=2,
            initial_policy='MLFQ', fallback_policy='MLFQ', explicit_no_switch=True,
            response_tail_protection=True, mlfq_quanta=(1, 2, 4), mlfq_aging_threshold=40)
        jobs = [Process('long', 0, 100), Process('new', 40, 2)]
        dynamic = run_dynamic(jobs, PriorityProposal(), config)
        static = run_simulation('MLFQ', mlfq, jobs, quanta=(1, 2, 4), aging_threshold=40)
        departure = next(d for d in dynamic.decisions if d.accepted and d.active == 'Priority')
        returned = next(d for d in dynamic.decisions if d.accepted and d.active == 'MLFQ')
        self.assertEqual(departure.features['first_service_ready_count'], 0)
        self.assertGreaterEqual(departure.features['arrival_quiet_ticks'], 20)
        self.assertGreater(returned.time - departure.time, 20)
        self.assertEqual(next(p.response_time for p in static.process_metrics if p.pid == 'new'), 0)
        self.assertEqual(next(p.response_time for p in dynamic.simulation.process_metrics if p.pid == 'new'), 60)

    def test_contention_descriptor_counts_pending_work_at_arrival(self):
        workload = {
            'exposure_ms': 100,
            'processes': [
                {'pid': 'a', 'arrival_time': 0, 'burst_time': 10, 'priority': 0},
                {'pid': 'b', 'arrival_time': 5, 'burst_time': 2, 'priority': 0},
                {'pid': 'c', 'arrival_time': 20, 'burst_time': 3, 'priority': 0},
            ],
        }
        result = characteristics(workload)
        self.assertEqual(result['arrival_work_pending_fraction'], 1 / 3)
        self.assertEqual(result['max_aggregate_pending_work_ms'], 10)
        self.assertEqual(result['total_cpu_proxy_ms'], 15)
        self.assertFalse(result['io_observed'])

    def test_shared_functions_link_hours_and_mixed_snapshots_transitively(self):
        def workload(name, functions):
            return {'workload_id': name, 'sources': [
                {'HashOwner': 'owner', 'HashApp': 'app', 'HashFunction': f}
                for f in functions]}
        workloads = [workload('hour', ['a']), workload('mixed', ['a', 'b']),
                     workload('snapshot', ['b']), workload('independent', ['c'])]
        groups = provenance_groups(workloads)
        self.assertEqual(groups['hour'], groups['snapshot'])
        self.assertEqual(groups['hour'], groups['mixed'])
        self.assertNotEqual(groups['hour'], groups['independent'])
        self.assertEqual(groups, provenance_groups(list(reversed(workloads))))


if __name__ == '__main__':
    unittest.main()
