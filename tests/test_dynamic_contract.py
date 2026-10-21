"""Regression contracts for decision-time observability and model compatibility."""

import copy
from pathlib import Path
import tempfile
import unittest

from autoscheduler.dynamic import (
    DYNAMIC_FEATURE_NAMES,
    DYNAMIC_SCHEMA_VERSION,
    DynamicRouterConfig,
    _dispatch,
    _new_state,
    _release,
    _run_to_completion,
    _simulation,
    extract_dynamic_features,
    run_dynamic,
)
from autoscheduler.evaluation import ALGORITHMS
from simulator.process import Process


class DynamicObservabilityTests(unittest.TestCase):
    def test_dynamic_schema_excludes_true_remaining_cpu(self):
        self.assertNotIn("remaining_cpu_mean", DYNAMIC_FEATURE_NAMES)
        self.assertNotIn("remaining_cpu_variance", DYNAMIC_FEATURE_NAMES)

    def test_features_ignore_declared_work_and_unobserved_future(self):
        state = _new_state([
            Process("ready", 0, 10, priority=2),
            Process("io", 0, 8, priority=1, cpu_bursts=(2, 6), io_bursts=(8,)),
            Process("future", 100, 5, priority=1),
        ])
        _release(state, 0)
        # Finish a known two-tick burst and observe the subsequent I/O block.
        _dispatch(state, "Priority", ALGORITHMS["Priority RR"][1])
        observed = extract_dynamic_features(state)
        altered = copy.deepcopy(state)
        for ready in altered.ready:
            ready.process.remaining_time = 999
            ready.process.burst_time = 2000
            ready.process.cpu_bursts = (2000,)
        for _, process, _, _ in altered.blocked:
            process.remaining_time = 777
            process.burst_time = 1554
            process.cpu_bursts = (777, 777)
            process.io_bursts = (999,)
        altered.pending = [Process("unseen", 10000, 99999, priority=99)]
        self.assertEqual(extract_dynamic_features(altered), observed)

    def test_completed_burst_statistics_count_full_service_across_quanta(self):
        state = _new_state([Process("A", 0, 7)])
        rr_config = {**ALGORITHMS["Priority RR"][1], "quantum": 2}
        _dispatch(state, "Round Robin", rr_config)
        self.assertEqual(state.completed_burst_durations, [])
        self.assertEqual(state.burst_service, {"A": 2})
        for _ in range(3):
            _dispatch(state, "Round Robin", rr_config)
        self.assertEqual(state.completed_burst_durations, [7])
        self.assertEqual(state.burst_service, {})

    def test_completed_history_is_available_even_when_queue_is_empty(self):
        state = _new_state([Process("A", 0, 7)])
        _dispatch(state, "FCFS", ALGORITHMS["Priority RR"][1])
        features = extract_dynamic_features(state)
        self.assertTrue(any(value for name, value in features.items() if "completed_burst" in name))

    def test_completed_bursts_and_observed_service_use_past_execution(self):
        state = _new_state([
            Process("A", 0, 8, cpu_bursts=(3, 5), io_bursts=(10,)),
            Process("B", 0, 9),
        ])
        rr_config = {**ALGORITHMS["Priority RR"][1], "quantum": 2}
        for _ in range(3):
            _dispatch(state, "Round Robin", rr_config)
        features = extract_dynamic_features(state)
        self.assertEqual(features["completed_burst_mean"], 3)
        self.assertEqual(features["completed_burst_variance"], 0)
        self.assertEqual(features["observed_service_mean"], 2.5)
        self.assertEqual(features["observed_service_variance"], 0.25)
        self.assertEqual(features["ready_count"], 1)
        self.assertEqual(features["blocked_count"], 1)


class _AlwaysSjf:
    def predict(self, rows):
        return ["SJF"] * len(rows)


class DynamicPolicyContractTests(unittest.TestCase):
    def test_evaluation_includes_eligible_baseline_and_schedule_regret(self):
        from autoscheduler.dynamic import evaluate_dynamic

        class AlwaysRr:
            def predict(self, rows):
                return ["Round Robin"] * len(rows)

        rows, summary = evaluate_dynamic(AlwaysRr(), traces=2, frozen_static_baseline="MLFQ")
        self.assertEqual(summary["frozen_static_baseline"], "MLFQ")
        self.assertIn("MLFQ", summary["mean_static_scores"])
        self.assertNotIn("SJF", summary["eligible_policies"])
        self.assertIn("mean_scheduling_regret", summary)
        self.assertIn("mean_starvation_count", summary)
        self.assertIn("decision_p99_ms", summary)
        self.assertEqual(rows[0]["weighted_score_adaptive"], rows[0]["weighted_score_round_robin"])

    def test_ineligible_frozen_comparator_is_rejected(self):
        from autoscheduler.dynamic import evaluate_dynamic

        with self.assertRaisesRegex(ValueError, "baseline|eligible|comparator"):
            evaluate_dynamic(_AlwaysSjf(), traces=1, frozen_static_baseline="SJF")

    def test_mlfq_dispatch_matches_existing_scheduler_on_preemption_io_and_aging(self):
        from scheduler.mlfq import mlfq
        from simulator.simulator import run_simulation

        workloads = [
            [Process("A", 0, 10), Process("B", 3, 1)],
            [Process("A", 0, 2, cpu_bursts=(1, 1), io_bursts=(2,)), Process("B", 0, 8)],
            [Process("A", 0, 3)] + [Process(f"P{time}", time, 1) for time in range(1, 22)]
            + [Process("P23", 23, 1)],
        ]
        for processes in workloads:
            with self.subTest(pids=tuple(process.pid for process in processes)):
                state = _new_state(processes)
                _run_to_completion(state, "MLFQ", ALGORITHMS["Priority RR"][1])
                actual = _simulation(state, "MLFQ")
                expected = run_simulation("MLFQ", mlfq, processes)
                self.assertEqual(actual.timeline, expected.timeline)
                self.assertEqual(actual.process_metrics, expected.process_metrics)

    def test_realistic_routing_rejects_true_burst_oracle_selection(self):
        with self.assertRaisesRegex(ValueError, "policy|algorithm|oracle"):
            run_dynamic([Process("A", 0, 20), Process("B", 0, 5)], _AlwaysSjf())

    def test_explicit_oracle_simulation_preserves_sjf_routing(self):
        config = DynamicRouterConfig(epoch_ticks=2, policy_track="oracle_simulation")
        result = run_dynamic([Process("A", 0, 20), Process("B", 0, 5)], _AlwaysSjf(), config)
        self.assertEqual(result.final_policy, "SJF")
        self.assertEqual(len(result.simulation.process_metrics), 2)

    def test_dynamic_training_automatically_groups_whole_trace_seeds(self):
        from autoscheduler.model import train_model

        rows = []
        for seed in range(8):
            for epoch in range(4):
                row = dict.fromkeys(DYNAMIC_FEATURE_NAMES, float(seed + epoch))
                row.update(seed=seed, epoch=epoch, label="FCFS")
                for policy in (*ALGORITHMS, "MLFQ"):
                    row[f"score_{policy.lower().replace(' ', '_')}"] = 0.0 if policy == "FCFS" else 1.0
                rows.append(row)
        with tempfile.TemporaryDirectory() as directory:
            report = train_model(
                rows, Path(directory) / "candidate.joblib", feature_names=DYNAMIC_FEATURE_NAMES,
                metadata={"dynamic_config": DynamicRouterConfig().__dict__},
            )
        self.assertEqual(report["split_group_key"], "seed")
        self.assertEqual(sum(report["split_trace_counts"].values()), 8)

    def test_dynamic_training_rejects_too_few_independent_traces(self):
        from autoscheduler.model import train_model

        rows = []
        for epoch in range(24):
            row = dict.fromkeys(DYNAMIC_FEATURE_NAMES, float(epoch))
            row.update(seed=epoch % 2, epoch=epoch, label="FCFS")
            for policy in (*ALGORITHMS, "MLFQ"):
                row[f"score_{policy.lower().replace(' ', '_')}"] = 0.0 if policy == "FCFS" else 1.0
            rows.append(row)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "four|4|trace|group"):
                train_model(
                    rows, Path(directory) / "candidate.joblib", feature_names=DYNAMIC_FEATURE_NAMES,
                    metadata={"dynamic_config": DynamicRouterConfig().__dict__},
                )


class DynamicPersistenceContractTests(unittest.TestCase):
    def _bundle(self):
        from autoscheduler.dynamic import dynamic_policy_parameters
        from sklearn.tree import DecisionTreeClassifier

        model = DecisionTreeClassifier(random_state=1).fit(
            [[0.0] * len(DYNAMIC_FEATURE_NAMES), [1.0] * len(DYNAMIC_FEATURE_NAMES)],
            ["FCFS", "Priority"],
        )
        return {
            "model": model,
            "features": DYNAMIC_FEATURE_NAMES,
            "metadata": {
                "schema_version": DYNAMIC_SCHEMA_VERSION,
                "policy_set": ["FCFS", "Round Robin", "Priority", "Priority RR", "MLFQ"],
                "dynamic_config": DynamicRouterConfig().__dict__,
                "priority_rr_config": dict(ALGORITHMS["Priority RR"][1]),
                "policy_parameters": dynamic_policy_parameters(DynamicRouterConfig(), ALGORITHMS["Priority RR"][1]),
            },
        }

    def _save_and_load(self, bundle, **kwargs):
        import joblib
        from autoscheduler.model import load_model

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidate.joblib"
            joblib.dump(bundle, path)
            return load_model(path, feature_names=DYNAMIC_FEATURE_NAMES, **kwargs)

    def test_valid_dynamic_bundle_loads_with_explicit_contract(self):
        bundle = self._bundle()
        model = self._save_and_load(
            bundle,
            expected_dynamic_config=DynamicRouterConfig(),
            expected_priority_rr_config=dict(ALGORITHMS["Priority RR"][1]),
        )
        self.assertEqual(list(model.predict([[0.0] * len(DYNAMIC_FEATURE_NAMES)])), ["FCFS"])

    def test_legacy_bundle_without_schema_version_requires_retraining(self):
        bundle = self._bundle()
        del bundle["metadata"]["schema_version"]
        with self.assertRaises(ValueError):
            self._save_and_load(bundle)

    def test_saved_five_policy_oracle_model_is_incompatible(self):
        bundle = self._bundle()
        bundle["metadata"]["policy_set"] = ["FCFS", "SJF", "Round Robin", "Priority", "Priority RR"]
        with self.assertRaises(ValueError):
            self._save_and_load(bundle)

    def test_dynamic_bundle_without_router_configuration_is_rejected(self):
        bundle = self._bundle()
        del bundle["metadata"]["dynamic_config"]
        with self.assertRaises(ValueError):
            self._save_and_load(bundle)

    def test_runtime_router_configuration_must_match_training(self):
        with self.assertRaises(ValueError):
            self._save_and_load(self._bundle(), expected_dynamic_config=DynamicRouterConfig(epoch_ticks=20))

    def test_runtime_rr_configuration_must_match_training(self):
        mismatched = {**ALGORITHMS["Priority RR"][1], "quantum": 17}
        with self.assertRaises(ValueError):
            self._save_and_load(self._bundle(), expected_priority_rr_config=mismatched)

    def test_saved_policy_parameters_must_match_current_code(self):
        bundle = self._bundle()
        bundle["metadata"]["policy_parameters"] = {"MLFQ": {"quanta": [99]}}
        with self.assertRaises(ValueError):
            self._save_and_load(bundle)

    def test_declared_schema_cannot_hide_incompatible_estimator_width(self):
        from sklearn.tree import DecisionTreeClassifier

        bundle = self._bundle()
        bundle["model"] = DecisionTreeClassifier().fit([[0.] * 8, [1.] * 8], ["FCFS", "Priority"])
        with self.assertRaisesRegex(ValueError, "feature|width|retrain"):
            self._save_and_load(bundle)

    def test_cost_estimator_requires_one_output_per_eligible_policy(self):
        from sklearn.tree import DecisionTreeRegressor
        from autoscheduler.model import PolicyCostModel

        bundle = self._bundle()
        estimator = DecisionTreeRegressor().fit([[0.] * len(DYNAMIC_FEATURE_NAMES)], [[0., 1.]])
        bundle["model"] = PolicyCostModel(estimator, tuple(bundle["metadata"]["policy_set"]))
        with self.assertRaisesRegex(ValueError, "output|polic|retrain"):
            self._save_and_load(bundle)

    def test_old_feature_argument_cannot_bypass_dynamic_contract(self):
        import joblib
        from autoscheduler.model import load_model

        bundle = self._bundle()
        bundle["features"] = ("remaining_cpu_mean",)
        bundle["metadata"]["policy_set"] = list(ALGORITHMS)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.joblib"
            joblib.dump(bundle, path)
            with self.assertRaises(ValueError):
                load_model(path, feature_names=bundle["features"])


class DynamicTrainingSafeguardTests(unittest.TestCase):
    def test_development_density_varies_independently_of_behavior_policy(self):
        from unittest.mock import patch
        from autoscheduler.dynamic import build_dynamic_dataset
        from collections import defaultdict

        counts = defaultdict(set)
        class EmptyWorkload:
            seed = 0
            processes = ()

        def generate(seed, process_count):
            index = seed - 42 * 1_000_000
            counts[index % 6].add(process_count)
            return EmptyWorkload()

        with patch("autoscheduler.dynamic.generate_dynamic_workload", side_effect=generate), \
                patch("autoscheduler.dynamic._training_states", return_value=[]):
            with self.assertRaisesRegex(ValueError, "no decision epochs"):
                build_dynamic_dataset(24, 42)
        self.assertEqual(list(counts.values()), [{3, 6, 12, 18}] * 6)

    def test_on_policy_rows_only_augment_training_trace_groups(self):
        from autoscheduler.dynamic_training import build_training_data
        from autoscheduler.model import _split_indexes

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "split.json"
            rows, report = build_training_data(4, 91, DynamicRouterConfig(20, 2, .8), path)
            self.assertTrue(path.exists())
        on_policy = [row for row in rows if row["behavior_policy"] == "adaptive"]
        self.assertTrue(on_policy)
        groups = report["groups"]
        self.assertLessEqual({row["seed"] for row in on_policy}, set(groups["train"]))
        splits = _split_indexes(rows, 91, "seed")
        self.assertEqual(groups, {name: sorted({rows[index]["seed"] for index in split})
                                  for name, split in zip(("train", "validation", "test"), splits)})

    def test_cost_tree_trains_and_loads_without_oracle_actions(self):
        from autoscheduler.dynamic import build_dynamic_dataset, DYNAMIC_POLICY_NAMES
        from autoscheduler.model import train_model, load_model

        config = DynamicRouterConfig(20, 2, .8)
        rows = build_dynamic_dataset(4, 91, config)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cost.joblib"
            report = train_model(rows, path, feature_names=DYNAMIC_FEATURE_NAMES,
                                 metadata={"dynamic_config": config.__dict__}, model_kind="policy_cost")
            model = load_model(path, DYNAMIC_FEATURE_NAMES)
            result = run_dynamic([Process("A", 0, 80), Process("B", 3, 5)], model, config)
            from autoscheduler.dynamic import evaluate_dynamic
            import json
            evaluation_rows, summary = evaluate_dynamic(model, traces=1, config=config)
            json.dumps({"rows": evaluation_rows, "summary": summary})
            self.assertIsNone(summary["mean_confidence"])
            self.assertIsNone(evaluation_rows[0]["mean_confidence"])
        self.assertEqual(report["status"], "SYNTHETIC_DEVELOPMENT_ONLY")
        self.assertEqual(model.policies, DYNAMIC_POLICY_NAMES)
        self.assertEqual(len(result.simulation.process_metrics), 2)
        self.assertIn("test_confusion_matrix", report)
        self.assertIn("test_tie_aware_accuracy", report)

    def test_confidence_dwell_and_dispatch_boundaries_remain_enforced(self):
        class LowConfidence(_AlwaysSjf):
            classes_ = ("FCFS", "Priority")

            def predict(self, rows):
                return ["FCFS"] * len(rows)

            def predict_proba(self, rows):
                return [[.51, .49]] * len(rows)

        config = DynamicRouterConfig(2, 3, .8)
        processes = [Process("A", 0, 30), Process("B", 1, 20)]
        held = run_dynamic(processes, LowConfidence(), config)
        self.assertTrue(held.decisions)
        self.assertFalse(any(decision.accepted for decision in held.decisions))

        class Confident(LowConfidence):
            def predict_proba(self, rows):
                return [[1., 0.]] * len(rows)

        result = run_dynamic(processes, Confident(), config)
        accepted = [decision for decision in result.decisions if decision.accepted]
        self.assertTrue(accepted)
        self.assertGreaterEqual(accepted[0].time, config.dwell_epochs * config.epoch_ticks)
        boundaries = {end for _, _, end in result.simulation.timeline}
        self.assertTrue(all(decision.time in boundaries for decision in result.decisions))


if __name__ == "__main__":
    unittest.main()
