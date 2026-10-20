import tempfile
import unittest
import os
import tempfile
from pathlib import Path

from autoscheduler.dynamic import RoutingDecision
from autoscheduler.evaluation import run_algorithm
from simulator.process import Process


class DynamicDemoTests(unittest.TestCase):
    def test_cli_exposes_one_command_with_safe_small_overrides(self):
        from autoscheduler.cli import build_parser

        arguments = build_parser().parse_args([
            "dynamic-demo", "--train-traces", "12", "--validation-traces", "6",
            "--demo-seed", "9090", "--output", "results/demo", "--artifacts", "artifacts/demo",
        ])

        self.assertEqual(arguments.command, "dynamic-demo")
        self.assertEqual(arguments.train_traces, 12)
        self.assertEqual(arguments.validation_traces, 6)
        self.assertEqual(arguments.demo_seed, 9090)

    def test_family_selection_uses_validation_score_then_configured_simplicity(self):
        from autoscheduler.dynamic_demo import select_family

        records = [
            {"family": "Decision Tree", "validation_score": 0.1000},
            {"family": "Ridge", "validation_score": 0.1004},
            {"family": "Random Forest", "validation_score": 0.1020},
        ]

        selected = select_family(
            records, ("Dummy", "Ridge", "Decision Tree", "Random Forest", "Histogram Gradient Boosting")
        )

        self.assertEqual(selected["family"], "Ridge")

    def test_decision_log_reconstructs_policy_before_and_after_each_review(self):
        from autoscheduler.dynamic_demo import decision_rows

        decisions = [
            RoutingDecision(10, "FCFS", "MLFQ", 0.4, False, "low_confidence", {}, 0.1),
            RoutingDecision(20, "Round Robin", "Round Robin", 0.9, True, "accepted", {}, 0.2),
        ]

        rows = decision_rows("MLFQ", decisions)

        self.assertEqual(rows[0]["active_before"], "MLFQ")
        self.assertEqual(rows[0]["active_after"], "MLFQ")
        self.assertEqual(rows[1]["active_before"], "MLFQ")
        self.assertEqual(rows[1]["active_after"], "Round Robin")

    def test_output_paths_must_be_fresh_to_avoid_colliding_with_evidence(self):
        from autoscheduler.dynamic_demo import require_fresh_paths

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            artifacts = root / "artifacts"
            output.mkdir()
            (output / "summary.json").write_text("{}", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "fresh"):
                require_fresh_paths(output, artifacts)

    def test_simulation_report_uses_existing_fairness_field_names(self):
        from autoscheduler.dynamic_demo import _simulation_metrics

        result = run_algorithm("FCFS", [Process("A", 0, 2)])

        metrics = _simulation_metrics(result, {"FCFS": result})

        self.assertEqual(metrics["p95_wait"], 0)

    def test_gantt_uses_a_reusable_writable_cache(self):
        from autoscheduler.dynamic_demo import _save_gantt

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gantt.png"
            previous = os.environ.pop("MPLCONFIGDIR", None)
            try:
                _save_gantt(path, [("A", 0, 1)])
                self.assertEqual(
                    os.environ["MPLCONFIGDIR"], str(Path(tempfile.gettempdir()) / "autoscheduler-matplotlib")
                )
                self.assertTrue(path.exists())
            finally:
                if previous is None:
                    os.environ.pop("MPLCONFIGDIR", None)
                else:
                    os.environ["MPLCONFIGDIR"] = previous


if __name__ == "__main__":
    unittest.main()
