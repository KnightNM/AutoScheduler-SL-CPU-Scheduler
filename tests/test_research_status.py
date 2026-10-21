import json
from pathlib import Path
import tempfile
import unittest


class ResearchStatusTests(unittest.TestCase):
    def fixture(self, root):
        folder = root / "results/dynamic_v6_20261019"
        folder.mkdir(parents=True)
        summary = {"status": "SYNTHETIC_DEVELOPMENT_ONLY", "promotion": False,
            "protocol": {"seeds": {"audit": 10603}, "traces": {"audit": 240}},
            "primary_baseline": "Tuned MLFQ", "tuned_parameters": {"quanta": [1, 2, 4]},
            "development_selected": "policy_cost", "accepted_after_audit": None,
            "acceptance": {"policy_cost": False}, "model_sha256": {},
            "audit": {"policy_cost": {"mean_score": .123, "mean_p95_response": 7.5,
                "gates": {"primary_p95": False}}, "Tuned MLFQ": {"mean_score": .15}}}
        (folder / "research_summary.json").write_text(json.dumps(summary))
        return folder, summary

    def test_metrics_are_sourced_and_unmeasured_latency_is_null(self):
        from autoscheduler.research_status import build_status
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            status = build_status(root)
            evaluation = status["evaluations"][0]
            metrics = evaluation["metrics"]["policy_cost"]
            self.assertEqual(metrics["weighted_score"], .123)
            self.assertEqual(metrics["p95_response"], 7.5)
            self.assertIsNone(metrics["decision_p99"])
            self.assertEqual(status["metric_definitions"]["p95_response"]["unit"], "simulator_tick")
            self.assertEqual(status["approved_ml_models"], [])
            self.assertFalse(evaluation["safety_gates"]["policy_cost"]["primary_p95"])

    def test_missing_or_changed_model_cannot_be_marked_validated(self):
        from autoscheduler.research_status import build_status
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder, summary = self.fixture(root)
            summary["model_sha256"] = {"policy_cost": "wrong"}
            (folder / "research_summary.json").write_text(json.dumps(summary))
            status = build_status(root)
            model = status["models"][0]
            self.assertFalse(model["artifact"]["validated"])
            path = root / model["artifact"]["path"]
            path.parent.mkdir(parents=True)
            path.write_bytes(b"changed model")
            model = build_status(root)["models"][0]
            self.assertFalse(model["artifact"]["validated"])
            self.assertEqual(model["status"], "experimental")

    def test_synthetic_gate_pass_is_not_deployment_approval(self):
        from autoscheduler.research_status import build_status
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder, summary = self.fixture(root)
            summary.update(accepted_after_audit="policy_cost", acceptance={"policy_cost": True}, promotion=True)
            (folder / "research_summary.json").write_text(json.dumps(summary))
            status = build_status(root)
            self.assertEqual(status["approved_ml_models"], [])
            self.assertEqual(status["synthetic_tuning"], "closed")


if __name__ == "__main__":
    unittest.main()
