import copy
import unittest

from autoscheduler.dynamic import (
    DYNAMIC_FEATURE_NAMES, DynamicRouterConfig, _new_state, _release, _dispatch,
    _counterfactual_label, extract_dynamic_features, run_dynamic,
)
from autoscheduler.evaluation import ALGORITHMS, compare_algorithms
from simulator.process import Process


class Constant:
    def __init__(self, action):
        self.action = action

    def predict(self, matrix):
        return [self.action] * len(matrix)


class ProtectionTests(unittest.TestCase):
    def config(self, **kwargs):
        return DynamicRouterConfig(epoch_ticks=2, dwell_epochs=2, initial_policy="MLFQ",
                                   fallback_policy="MLFQ", explicit_no_switch=True, **kwargs)

    def test_first_service_guard_blocks_only_until_observed_first_allocations(self):
        processes = [Process(str(i), 0, 30) for i in range(6)]
        result = run_dynamic(processes, Constant("FCFS"), self.config())
        blocked = [d for d in result.decisions if d.reason == "first_service_protection"]
        self.assertTrue(blocked)
        self.assertTrue(all(not d.accepted for d in blocked))
        accepted = [d for d in result.decisions if d.accepted]
        self.assertTrue(accepted)
        self.assertGreaterEqual(accepted[0].time, 12)
        self.assertTrue(all(d.features["first_service_ready_count"] == 0 for d in accepted))

    def test_no_switch_is_explicit_and_preserves_policy(self):
        result = run_dynamic([Process("a", 0, 80), Process("b", 0, 30)],
                             Constant("No Switch"), self.config())
        self.assertEqual(result.final_policy, "MLFQ")
        self.assertFalse(any(d.accepted for d in result.decisions))

    def test_observed_quantiles_and_first_service_ignore_hidden_definitions(self):
        state = _new_state([Process("a", 0, 80), Process("b", 0, 30), Process("future", 99, 1)])
        _dispatch(state, "MLFQ", ALGORITHMS["Priority RR"][1])
        features = extract_dynamic_features(state, "MLFQ")
        self.assertEqual(features["first_service_ready_count"], 1)
        self.assertEqual(features["first_service_wait_max"], 2)
        self.assertEqual(features["ready_wait_p50"], 1)
        self.assertAlmostEqual(features["ready_wait_p95"], 1.9)
        other = copy.deepcopy(state)
        other.pending[0].arrival_time = 999
        for item in other.ready:
            item.process.remaining_time = 9999
            item.process.cpu_bursts = (9999,)
            item.process.io_bursts = ()
        self.assertEqual(features, extract_dynamic_features(other, "MLFQ"))
        self.assertEqual(tuple(features), DYNAMIC_FEATURE_NAMES)

    def test_infeasible_departures_label_as_no_switch(self):
        processes = [Process(str(i), 0, 30) for i in range(6)]
        config = self.config()
        state = _new_state(processes, config)
        _release(state, 0)
        from autoscheduler.dynamic import dynamic_action_names
        label, costs = _counterfactual_label(state, 2, ALGORITHMS["Priority RR"][1],
            dynamic_action_names(config), "MLFQ", config=config, references=compare_algorithms(processes))
        self.assertEqual(label, "No Switch")
        self.assertTrue(all(abs(cost) < 1e-12 for cost in costs.values()))

    def test_tuned_mlfq_fallback_matches_continuous_static_control(self):
        from scheduler.mlfq import mlfq
        from simulator.simulator import run_simulation
        from autoscheduler.development_workloads import generate_development_workload
        config = self.config(mlfq_quanta=(1, 2, 4), mlfq_aging_threshold=40)
        for family in ("cohort_mix", "long_io", "repeated_changes"):
            processes = generate_development_workload(71, family, 12).processes
            actual = run_dynamic(processes, None, config).simulation
            expected = run_simulation("MLFQ", mlfq, processes, quanta=(1, 2, 4), aging_threshold=40)
            self.assertEqual(actual.timeline, expected.timeline)
            self.assertEqual(actual.process_metrics, expected.process_metrics)

    def test_safety_eligibility_precedes_score_in_selection(self):
        from autoscheduler.model import scheduling_candidate_key
        self.assertLess(scheduling_candidate_key({"validation_schedule_eligible": True,
            "validation_schedule_score": .2}), scheduling_candidate_key({
            "validation_schedule_eligible": False, "validation_schedule_score": .1}))

    def test_no_model_cannot_claim_strict_improvement_over_identical_mlfq(self):
        from autoscheduler.dynamic_training import prepare_validation, validation_metrics
        config = self.config()
        cases, _ = prepare_validation(2, 18, config, development="v4")
        metrics = validation_metrics(None, cases, config,
            baseline_results=[static["MLFQ"] for _, static, _ in cases])
        self.assertFalse(metrics["validation_schedule_eligible"])
        self.assertFalse(metrics["validation_schedule_gates"]["score"])
        self.assertTrue(metrics["validation_schedule_gates"]["p95_response"])

    def test_six_action_cost_bundle_roundtrip_and_no_switch(self):
        import tempfile
        from pathlib import Path
        from autoscheduler.dynamic import dynamic_action_names
        from autoscheduler.model import train_model, load_model
        config = self.config()
        rows = []
        for seed in range(8):
            for epoch in range(4):
                row = dict.fromkeys(DYNAMIC_FEATURE_NAMES, 0.)
                row.update(seed=seed, epoch=epoch, label="No Switch")
                for action in dynamic_action_names(config):
                    row["score_" + action.lower().replace(" ", "_")] = 0. if action == "No Switch" else 1.
                rows.append(row)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.joblib"
            report = train_model(rows, path, feature_names=DYNAMIC_FEATURE_NAMES,
                metadata={"dynamic_config": config.__dict__, "static_baseline": "MLFQ"},
                model_kind="policy_cost", candidate_settings=[(3, 10, None)], refit=False)
            model = load_model(path, DYNAMIC_FEATURE_NAMES)
            result = run_dynamic([Process("a", 0, 60)], model, config)
            self.assertEqual(model.predict_benefits([[0.] * len(DYNAMIC_FEATURE_NAMES)])[0]["No Switch"], 0)
        self.assertEqual(len(model.policies), 6)
        self.assertEqual(len(report["policy_set"]), 5)
        self.assertFalse(any(d.accepted for d in result.decisions))

    def test_development_v4_is_reproducible_and_includes_sparse_long_io_counterexample(self):
        from autoscheduler.development_workloads import DEV_FAMILIES, generate_development_workload_v4
        from autoscheduler.evaluation import run_algorithm, score_result_against_reference
        counts = set()
        for seed in range(12):
            for family in DEV_FAMILIES:
                a = generate_development_workload_v4(seed, family)
                b = generate_development_workload_v4(seed, family)
                self.assertEqual(a, b)
                counts.add(len(a.processes))
        self.assertEqual(counts, {3, 6, 12, 24, 48})
        workload = generate_development_workload_v4(2, "long_io", 3)
        refs = compare_algorithms(workload.processes)
        self.assertLess(score_result_against_reference(refs["FCFS"], refs),
                        score_result_against_reference(run_algorithm("MLFQ", workload.processes), refs))


if __name__ == "__main__":
    unittest.main()
