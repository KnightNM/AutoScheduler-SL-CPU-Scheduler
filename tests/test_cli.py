import subprocess
import sys
import tempfile
import unittest
import json
import csv
from pathlib import Path


class CliTests(unittest.TestCase):
    def run_cli(self, *arguments):
        return subprocess.run(
            [sys.executable, "main.py", *map(str, arguments)],
            check=True,
            capture_output=True,
            text=True,
        )

    def test_train_compare_and_evaluate_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "model.joblib"
            dataset = root / "training.csv"
            results = root / "results"

            trained = self.run_cli(
                "train",
                "--samples-per-profile",
                5,
                "--model",
                model,
                "--dataset",
                dataset,
            )
            self.assertIn("Test accuracy", trained.stdout)
            self.assertIn("Validation regret", trained.stdout)
            self.assertTrue(model.exists())
            self.assertTrue(dataset.exists())
            model_report = json.loads(model.with_suffix(".json").read_text())
            self.assertEqual(len(model_report["priority_rr_tuning"]["candidates"]), 9)
            self.assertIn(model_report["static_baseline"], model_report["policy_set"])
            self.assertEqual(len(model_report["policy_set"]), 6)
            self.assertIn("SRTF", model_report["policy_set"])
            with dataset.open(newline="", encoding="utf-8") as file:
                self.assertIn("score_srtf", next(csv.DictReader(file)))

            compared = self.run_cli(
                "compare", "--profile", "mixed", "--seed", 77, "--model", model
            )
            self.assertIn("Adaptive selected", compared.stdout)
            self.assertIn("CPU utilization", compared.stdout)

            evaluated = self.run_cli(
                "evaluate",
                "--samples-per-profile",
                1,
                "--model",
                model,
                "--output",
                results,
            )
            self.assertIn("Best static", evaluated.stdout)
            self.assertIn("Adaptive beats SJF", evaluated.stdout)
            self.assertIn("Priority RR beats SJF", evaluated.stdout)
            self.assertIn("Statistically beats static", evaluated.stdout)
            self.assertTrue((results / "evaluation.csv").exists())
            self.assertTrue((results / "summary.json").exists())
            self.assertTrue((results / "scores.png").exists())
            self.assertTrue((results / "confusion_matrix.csv").exists())
            self.assertTrue((results / "feature_importance.csv").exists())
            self.assertTrue((results / "diagnostics.png").exists())
            self.assertTrue((results / "fairness_metrics.csv").exists())
            self.assertTrue((results / "fairness.png").exists())
            summary = json.loads((results / "summary.json").read_text())
            self.assertEqual(summary["frozen_static_baseline"], model_report["static_baseline"])
            self.assertIn("SRTF", summary["static_policies"])

            latency = self.run_cli(
                "latency",
                "--samples-per-profile",
                1,
                "--warmups",
                0,
                "--model",
                model,
                "--score-summary",
                results / "summary.json",
                "--output",
                results,
            )
            self.assertIn("Recommended policy", latency.stdout)
            self.assertTrue((results / "latency.csv").exists())
            self.assertTrue((results / "latency_summary.json").exists())
            self.assertTrue((results / "latency.png").exists())
            with (results / "latency.csv").open(newline="", encoding="utf-8") as file:
                self.assertEqual(len(list(csv.DictReader(file))), 18)

            dynamic_model = root / "dynamic.joblib"
            dynamic_dataset = root / "dynamic.csv"
            dynamic_results = root / "dynamic-results"
            dynamic_trained = self.run_cli(
                "dynamic-train",
                "--traces", 2,
                "--tuning-traces", 1,
                "--model", dynamic_model,
                "--dataset", dynamic_dataset,
            )
            self.assertIn("Router config", dynamic_trained.stdout)
            self.assertTrue(dynamic_model.exists())

            dynamic_evaluated = self.run_cli(
                "dynamic-evaluate", "--traces", 2, "--model", dynamic_model, "--output", dynamic_results
            )
            self.assertIn("P95 response gate", dynamic_evaluated.stdout)
            self.assertTrue((dynamic_results / "dynamic_evaluation.csv").exists())
            self.assertTrue((dynamic_results / "dynamic_summary.json").exists())
            self.assertTrue((dynamic_results / "dynamic_diagnostics.png").exists())


if __name__ == "__main__":
    unittest.main()
