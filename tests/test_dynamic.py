import unittest

from autoscheduler.dynamic import (
    DYNAMIC_FEATURE_NAMES,
    DynamicRouterConfig,
    build_dynamic_dataset,
    evaluate_dynamic,
    generate_dynamic_workload,
    run_dynamic,
    _new_state,
    _run_to_completion,
    _simulation,
)
from autoscheduler.evaluation import ALGORITHMS, run_algorithm
from simulator.process import Process


class _RoundRobinModel:
    def predict(self, rows):
        return ["Round Robin" for _ in rows]

    def predict_proba(self, rows):
        return [[0.0, 0.0, 1.0, 0.0, 0.0] for _ in rows]

    classes_ = ("FCFS", "Priority", "Round Robin", "Priority RR", "SJF")


class _SjfModel(_RoundRobinModel):
    def predict(self, rows):
        return ["SJF" for _ in rows]

    def predict_proba(self, rows):
        return [[0.0, 0.0, 0.0, 0.0, 1.0] for _ in rows]


class _SrtfModel(_RoundRobinModel):
    def predict(self, rows):
        return ["SRTF" for _ in rows]


class DynamicRoutingTests(unittest.TestCase):
    def test_static_and_dynamic_dispatch_agree_for_sjf_and_srtf(self):
        processes = [
            Process("A", 0, 10, cpu_bursts=(2, 8), io_bursts=(3,)),
            Process("B", 0, 6),
            Process("C", 2, 1),
        ]
        for policy in ("SJF", "SRTF"):
            with self.subTest(policy=policy):
                state = _new_state(processes)
                _run_to_completion(state, policy, ALGORITHMS["Priority RR"][1])
                actual = _simulation(state, policy)
                expected = run_algorithm(policy, processes)
                self.assertEqual(actual.timeline, expected.timeline)
                self.assertEqual(actual.context_switches, expected.context_switches)
                self.assertEqual(actual.process_metrics, expected.process_metrics)

    def test_dynamic_router_accepts_srtf(self):
        workload = generate_dynamic_workload(14, process_count=3)
        result = run_dynamic(workload.processes, _SrtfModel(), DynamicRouterConfig(epoch_ticks=5, confidence_threshold=0.6))
        self.assertEqual(result.final_policy, "SRTF")
        self.assertEqual(len(result.simulation.process_metrics), len(workload.processes))
        self.assertTrue(any(decision.accepted for decision in result.decisions))

    def test_three_distinct_cohorts_are_reproducible(self):
        first = generate_dynamic_workload(42)
        second = generate_dynamic_workload(42)
        self.assertEqual(first, second)
        self.assertEqual(first.phase_profiles[0], first.processes[0].pid.split("_")[0].lower())
        self.assertEqual({process.arrival_time // 20 for process in first.processes}, {0, 1, 2})
        self.assertEqual(len(first.phase_profiles), len(set(first.phase_profiles)))

    def test_router_preserves_processes_and_holds_on_rejected_switches(self):
        workload = generate_dynamic_workload(7, process_count=3)
        result = run_dynamic(
            workload.processes,
            _RoundRobinModel(),
            DynamicRouterConfig(epoch_ticks=5, dwell_epochs=3, confidence_threshold=1.0),
        )
        self.assertEqual(
            {metric.pid for metric in result.simulation.process_metrics},
            {process.pid for process in workload.processes},
        )
        self.assertEqual(result.initial_policy, "Round Robin")
        self.assertTrue(result.decisions)
        self.assertTrue(all(decision.selected == "Round Robin" for decision in result.decisions))
        self.assertEqual(tuple(result.decisions[0].features), DYNAMIC_FEATURE_NAMES)
        self.assertGreaterEqual(result.transition_p99_ms, 0.0)

    def test_dynamic_rows_train_and_evaluate_with_state_features(self):
        from autoscheduler.model import load_model, train_model

        config = DynamicRouterConfig(epoch_ticks=5, dwell_epochs=1, confidence_threshold=0.0)
        rows = build_dynamic_dataset(traces=2, seed=12, config=config)
        self.assertTrue(rows)
        self.assertEqual(tuple(name for name in DYNAMIC_FEATURE_NAMES if name in rows[0]), DYNAMIC_FEATURE_NAMES)
        with __import__("tempfile").TemporaryDirectory() as directory:
            path = __import__("pathlib").Path(directory) / "dynamic.joblib"
            train_model(rows, path, feature_names=DYNAMIC_FEATURE_NAMES, metadata={"dynamic_config": config.__dict__})
            model = load_model(path, feature_names=DYNAMIC_FEATURE_NAMES)
            _, summary = evaluate_dynamic(model, traces=2, seed=13, config=config)
        self.assertIn("p95_response_gate", summary)
        self.assertIn("weighted_score_gate", summary)
        self.assertIn("latency_gate", summary)

    def test_accepted_switch_keeps_every_process_and_records_full_path_timing(self):
        workload = generate_dynamic_workload(14, process_count=3)
        result = run_dynamic(
            workload.processes, _SjfModel(), DynamicRouterConfig(epoch_ticks=5, confidence_threshold=0.6)
        )
        self.assertTrue(any(decision.accepted for decision in result.decisions))
        self.assertEqual(result.final_policy, "SJF")
        self.assertEqual(len(result.simulation.process_metrics), len(workload.processes))
        self.assertTrue(all(decision.transition_ms >= 0 for decision in result.decisions))


if __name__ == "__main__":
    unittest.main()
