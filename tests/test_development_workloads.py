"""Development diversity must not mutate the frozen evaluation generator."""

import unittest
from unittest.mock import patch

from autoscheduler.dynamic import generate_dynamic_workload
from autoscheduler.evaluation import run_algorithm


FAMILIES = (
    "cohort_mix", "sustained_arrivals", "low_load", "long_io",
    "repeated_changes", "homogeneous_batch",
)


def signature(workload):
    return tuple((p.pid, p.arrival_time, p.burst_time, p.priority, p.cpu_bursts, p.io_bursts)
                 for p in workload.processes)


class DevelopmentWorkloadTests(unittest.TestCase):
    def generate(self, seed=123, family=None, process_count=None):
        from autoscheduler.development_workloads import generate_development_workload

        return generate_development_workload(seed, family=family, process_count=process_count)

    def test_named_families_and_seeded_metadata_are_reproducible(self):
        from autoscheduler.development_workloads import DEV_FAMILIES

        self.assertEqual(tuple(DEV_FAMILIES), FAMILIES)
        for family in (*FAMILIES, None):
            with self.subTest(family=family):
                first = self.generate(family=family)
                second = self.generate(family=family)
                self.assertEqual(first.seed, 123)
                self.assertIn(first.family, FAMILIES)
                if family is not None:
                    self.assertEqual(first.family, family)
                self.assertEqual(first.family, second.family)
                self.assertIsInstance(first.phase_profiles, tuple)
                self.assertTrue(first.phase_profiles)
                self.assertTrue(all(isinstance(profile, str) for profile in first.phase_profiles))
                self.assertEqual(first.phase_profiles, second.phase_profiles)
                self.assertEqual(signature(first), signature(second))
                self.assertTrue(first.processes)
                self.assertEqual(len({p.pid for p in first.processes}), len(first.processes))

    def test_invalid_family_and_nonpositive_counts_are_rejected(self):
        with self.assertRaises(ValueError):
            self.generate(family="unknown")
        for count in (0, -1):
            for family in FAMILIES:
                with self.subTest(count=count, family=family):
                    with self.assertRaises(ValueError):
                        self.generate(family=family, process_count=count)

    def test_sustained_arrivals_extend_beyond_frozen_initial_congestion(self):
        workload = self.generate(family="sustained_arrivals", process_count=24)
        arrivals = [p.arrival_time for p in workload.processes]
        self.assertEqual(len(arrivals), 24)
        self.assertGreaterEqual(max(arrivals) - min(arrivals), 100)

    def test_low_load_contains_late_arrivals_without_ready_queue_backlog(self):
        workload = self.generate(family="low_load", process_count=12)
        arrivals = [p.arrival_time for p in workload.processes]
        self.assertEqual(len(arrivals), 12)
        self.assertGreaterEqual(max(arrivals) - min(arrivals), 500)
        result = run_algorithm("FCFS", workload.processes)
        self.assertEqual(result.avg_waiting_time, 0)

    def test_long_io_includes_returns_absent_from_short_io_regimes(self):
        workload = self.generate(family="long_io", process_count=12)
        self.assertGreaterEqual(max(duration for p in workload.processes for duration in p.io_bursts), 50)

    def test_repeated_changes_contain_five_separated_cohorts(self):
        workload = self.generate(family="repeated_changes", process_count=20)
        arrivals = sorted(p.arrival_time for p in workload.processes)
        self.assertEqual(len(arrivals), 20)
        self.assertGreaterEqual(max(arrivals), 400)
        self.assertGreaterEqual(sum(later - earlier >= 50 for earlier, later in zip(arrivals, arrivals[1:])), 4)

    def test_homogeneous_batch_is_a_uniform_cpu_only_control(self):
        workload = self.generate(family="homogeneous_batch", process_count=12)
        self.assertEqual(len({p.cpu_bursts for p in workload.processes}), 1)
        self.assertTrue(all(not p.io_bursts for p in workload.processes))

    def test_development_dataset_crosses_each_family_with_every_behavior(self):
        from collections import Counter
        from autoscheduler.development_workloads import generate_development_workload
        from autoscheduler.dynamic import DYNAMIC_POLICY_NAMES, build_dynamic_dataset

        families, pairs = {}, Counter()

        def generate(seed, family=None, process_count=None):
            workload = generate_development_workload(seed, family, process_count)
            families[seed] = workload.family
            return workload

        def states(processes, config, rr_config, behavior, seed, behavior_model):
            pairs[(families[seed], behavior)] += 1
            return []

        with patch("autoscheduler.development_workloads.generate_development_workload", side_effect=generate), \
                patch("autoscheduler.dynamic.generate_dynamic_workload", side_effect=AssertionError("frozen generator used")), \
                patch("autoscheduler.dynamic.compare_algorithms", return_value={}), \
                patch("autoscheduler.dynamic._training_states", side_effect=states):
            with self.assertRaisesRegex(ValueError, "no decision epochs"):
                build_dynamic_dataset(36, 42, development=True)
        self.assertEqual(set(families), set(range(42000000, 42000036)))
        self.assertEqual(pairs, Counter({(family, behavior): 1 for family in FAMILIES
                                        for behavior in (*DYNAMIC_POLICY_NAMES, "explore")}))

    def test_development_dataset_marks_family_and_excludes_dwell_blocked_rows(self):
        from autoscheduler.dynamic import DynamicRouterConfig, build_dynamic_dataset

        config = DynamicRouterConfig(epoch_ticks=10, dwell_epochs=2, initial_policy="MLFQ", fallback_policy="MLFQ")
        rows = build_dynamic_dataset(2, 42, config, trace_indexes=(6, 12), development=True)
        self.assertEqual({row["seed"] for row in rows}, {42000006, 42000012})
        self.assertEqual({row["development_family"] for row in rows}, {"sustained_arrivals", "low_load"})
        self.assertTrue(all(row["dwell_remaining_ticks"] == 0 for row in rows))

    def test_frozen_evaluation_seed_retains_original_process_definitions(self):
        workload = generate_dynamic_workload(314159, process_count=3)
        self.assertEqual(workload.phase_profiles, ("batch", "cpu_intensive", "mixed"))
        self.assertEqual(signature(workload), (
            ("batch_1", 0, 12, 3, (12,), ()),
            ("batch_2", 0, 16, 2, (16,), ()),
            ("batch_3", 0, 10, 1, (10,), ()),
            ("cpu_intensive_1", 20, 30, 2, (13, 17), (1,)),
            ("cpu_intensive_2", 22, 41, 5, (14, 27), (2,)),
            ("cpu_intensive_3", 24, 29, 2, (29,), ()),
            ("mixed_1", 40, 6, 5, (1, 3, 2), (5, 7)),
            ("mixed_2", 40, 6, 4, (3, 1, 2), (4, 9)),
            ("mixed_3", 40, 8, 2, (3, 1, 4), (5, 6)),
        ))


if __name__ == "__main__":
    unittest.main()
