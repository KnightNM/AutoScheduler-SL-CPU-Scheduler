import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from autoscheduler.real_features import FEATURE_NAMES


def _rows(trace_count=6):
    rows = []
    for trace in range(trace_count):
        for decision in range(3):
            for action, cost in (("FCFS", 0.8), ("Round Robin", 0.2), ("Priority", 0.6), ("Priority RR", 0.5), ("MLFQ", 0.4)):
                rows.append({
                    "trace_id": f"trace-{trace}", "application": f"app-{trace}", "scenario": f"scenario-{trace}",
                    "configuration_id": f"scenario-{trace}", "capture_session": "pilot",
                    "decision_timestamp_ns": str(decision), "action": action, "policy_cost": str(cost),
                    "label_provenance": "pilot_offline_replay_development_only", "source_result": f"trace-{trace}:{action}",
                    **{name: str(float(trace + decision)) for name in FEATURE_NAMES},
                })
    return rows


class ModelBakeoffReportTests(unittest.TestCase):
    def test_balanced_small_dataset_is_sufficient_for_prototype_comparison_only(self):
        from autoscheduler.real_bakeoff import run_prototype_bakeoff
        from autoscheduler.real_config import load_real_config

        with TemporaryDirectory() as directory:
            root = Path(directory)
            report = run_prototype_bakeoff(_rows(18), load_real_config(), root)

            self.assertEqual(
                report["prototype_sufficiency"]["status"],
                "SUFFICIENT_FOR_PROTOTYPE_COMPARISON",
            )
            self.assertEqual(report["gates"]["status"], "INSUFFICIENT_DATA")
            markdown = (root / "prototype_comparison_report.md").read_text(encoding="utf-8")
            self.assertIn("SUFFICIENT FOR PROTOTYPE COMPARISON", markdown)

    def test_report_selects_an_action_per_snapshot_and_writes_json_csv(self):
        from autoscheduler.real_bakeoff import run_prototype_bakeoff
        from autoscheduler.real_config import load_real_config

        with TemporaryDirectory() as directory:
            report = run_prototype_bakeoff(_rows(), load_real_config(), Path(directory))
            saved = json.loads((Path(directory) / "summary.json").read_text(encoding="utf-8"))

            self.assertEqual(report, saved)
            self.assertEqual(report["label_provenance"], "pilot_offline_replay_development_only")
            self.assertEqual(set(report["actions"]), {"FCFS", "Round Robin", "Priority", "Priority RR", "MLFQ"})
            self.assertIn("selected", report["bakeoff"])
            self.assertEqual(set(report["model_comparison"]), {"Dummy", "Ridge", "Decision Tree", "Random Forest", "Histogram Gradient Boosting"})
            self.assertIn("test_cost_mae", report["model_comparison"]["Ridge"])
            self.assertIn("action_selection_accuracy", report["model_comparison"]["Ridge"])
            self.assertIn("decision_p99_ms", report["model_comparison"]["Ridge"])
            self.assertEqual(report["model_comparison"]["Dummy"]["action_selection_accuracy"], 0.0)
            self.assertIn("locked_test_fixed_action_cost", report["comparison"])
            self.assertIn("locked_test_oracle_cost", report["comparison"])
            self.assertEqual(report["gates"]["status"], "INSUFFICIENT_DATA")
            self.assertEqual(report["gates"]["fairness_gate"], "UNAVAILABLE")
            self.assertTrue((Path(directory) / "candidates.csv").exists())
            self.assertTrue((Path(directory) / "prototype_comparison_report.md").exists())
            self.assertIn("## Feature method", (Path(directory) / "prototype_comparison_report.md").read_text(encoding="utf-8"))
            self.assertTrue((Path(directory) / "locked_evaluation_report.md").exists())

    def test_report_rejects_mixed_label_provenance(self):
        from autoscheduler.real_bakeoff import run_prototype_bakeoff
        from autoscheduler.real_config import load_real_config

        rows = _rows()
        rows[0]["label_provenance"] = "other"
        with TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "one label provenance"):
                run_prototype_bakeoff(rows, load_real_config(), Path(directory))

    def test_fairness_unavailable_prevents_a_pass_after_data_threshold(self):
        from autoscheduler.real_bakeoff import run_prototype_bakeoff
        from autoscheduler.real_config import load_real_config

        config = load_real_config()
        config["data"]["configurations"] = 5
        config["data"]["repetitions_per_configuration"] = 1
        with TemporaryDirectory() as directory:
            report = run_prototype_bakeoff(_rows(), config, Path(directory))

        self.assertTrue(report["gates"]["data_sufficient"])
        self.assertEqual(report["gates"]["fairness_gate"], "UNAVAILABLE")
        self.assertEqual(report["gates"]["status"], "FAIL")

    def test_synthetic_provenance_never_receives_a_deployment_status(self):
        from autoscheduler.real_bakeoff import run_prototype_bakeoff
        from autoscheduler.real_config import load_real_config

        rows = _rows()
        for row in rows:
            row["label_provenance"] = "synthetic_development_only"
        config = load_real_config()
        config["data"].update({"configurations": 5, "repetitions_per_configuration": 1})
        with TemporaryDirectory() as directory:
            report = run_prototype_bakeoff(rows, config, Path(directory))

        self.assertEqual(report["gates"]["status"], "SYNTHETIC_DEVELOPMENT_ONLY")


if __name__ == "__main__":
    unittest.main()
