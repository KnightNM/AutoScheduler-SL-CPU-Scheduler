import tempfile
import unittest
from pathlib import Path

from autoscheduler.adaptive import run_adaptive
from autoscheduler.dataset import build_dataset
from autoscheduler.evaluation import ALGORITHMS, SELECTOR_ALGORITHMS, run_algorithm
from autoscheduler.features import FEATURE_NAMES
from autoscheduler.workloads import generate_workload


class _FixedModel:
    def predict(self, rows):
        return ["FCFS" for _ in rows]


class _FixedPriorityRrModel:
    def predict(self, rows):
        return ["Priority RR" for _ in rows]


class _FixedSrtfModel:
    def predict(self, rows):
        return ["SRTF" for _ in rows]


class LearningTests(unittest.TestCase):
    def test_candidate_selection_prefers_regret_over_accuracy(self):
        from autoscheduler.model import _candidate_key

        lower_accuracy_lower_regret = {
            "validation_accuracy": 0.50,
            "validation_mean_regret": 0.01,
            "min_samples_leaf": 10,
        }
        higher_accuracy_higher_regret = {
            "validation_accuracy": 0.90,
            "validation_mean_regret": 0.02,
            "min_samples_leaf": 1,
        }
        self.assertLess(
            _candidate_key(lower_accuracy_lower_regret, 1),
            _candidate_key(higher_accuracy_higher_regret, 0),
        )
        self.assertLess(
            _candidate_key({**lower_accuracy_lower_regret, "min_samples_leaf": 10}, 0),
            _candidate_key({**lower_accuracy_lower_regret, "min_samples_leaf": 1}, 0),
        )

    def test_dataset_has_unique_reproducible_seeds(self):
        config = {"quantum": 1, "aging_interval": 4, "context_switch_cost": 1}
        first = build_dataset(samples_per_profile=2, seed=42, priority_rr_config=config)
        second = build_dataset(samples_per_profile=2, seed=42, priority_rr_config=config)
        self.assertEqual(first, second)
        self.assertEqual(len({row["seed"] for row in first}), len(first))
        self.assertTrue({row["label"] for row in first}.issubset(SELECTOR_ALGORITHMS))
        self.assertEqual(set(SELECTOR_ALGORITHMS), set(ALGORITHMS))
        self.assertTrue(
            {f"score_{name.lower().replace(' ', '_')}" for name in ALGORITHMS}.issubset(first[0])
        )

    def test_adaptive_result_matches_selected_static_algorithm(self):
        workload = generate_workload("mixed", 91, 10)
        adaptive = run_adaptive(workload.processes, _FixedModel())
        direct = run_algorithm("FCFS", workload.processes)
        self.assertEqual(adaptive.selected_algorithm, "FCFS")
        self.assertEqual(adaptive.simulation, direct)
        self.assertEqual(tuple(adaptive.features), FEATURE_NAMES)
        self.assertGreaterEqual(adaptive.inference_ms, 0)

    def test_adaptive_uses_frozen_priority_rr_configuration(self):
        workload = generate_workload("interactive", 92, 8)
        config = {"quantum": 1, "aging_interval": 4, "context_switch_cost": 1}
        adaptive = run_adaptive(workload.processes, _FixedPriorityRrModel(), config)
        direct = run_algorithm("Priority RR", workload.processes, config)
        self.assertEqual(adaptive.simulation, direct)

    def test_adaptive_srtf_matches_direct_execution(self):
        workload = generate_workload("interactive", 92, 8)
        adaptive = run_adaptive(workload.processes, _FixedSrtfModel())
        self.assertEqual(adaptive.simulation, run_algorithm("SRTF", workload.processes))

    def test_small_decision_tree_can_train_save_and_load(self):
        try:
            from autoscheduler.model import load_model, load_model_metadata, train_model
        except ModuleNotFoundError as error:
            self.skipTest(str(error))

        rows = build_dataset(samples_per_profile=20, seed=100)
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "model.joblib"
            config = {"quantum": 1, "aging_interval": 4, "context_switch_cost": 1}
            report = train_model(rows, model_path, random_state=100, priority_rr_config=config)
            model = load_model(model_path)
            metadata = load_model_metadata(model_path)
            prediction = model.predict([[rows[0][name] for name in FEATURE_NAMES]])[0]
            self.assertTrue(model_path.exists())
            self.assertIn(prediction, {row["label"] for row in rows})
            self.assertGreaterEqual(report["test_accuracy"], 0)
            self.assertLessEqual(report["test_accuracy"], 1)
            self.assertGreaterEqual(report["validation_mean_regret"], 0)
            self.assertGreaterEqual(report["test_mean_regret"], 0)
            self.assertEqual(set(report["feature_importance"]), set(FEATURE_NAMES))
            self.assertEqual(metadata["priority_rr_config"], config)
            self.assertIn(metadata["static_baseline"], ALGORITHMS)
            import joblib
            saved = joblib.load(model_path)
            saved["metadata"]["policy_set"].remove("SRTF")
            joblib.dump(saved, model_path)
            with self.assertRaisesRegex(ValueError, "retrain"):
                load_model(model_path)


if __name__ == "__main__":
    unittest.main()
