"""Diagnostics must reproduce the frozen implementation without fitting models."""

from pathlib import Path
import unittest

from autoscheduler.dynamic import (
    DYNAMIC_FEATURE_NAMES, DYNAMIC_POLICY_NAMES, DynamicRouterConfig, _counterfactual_label, _new_state,
    _policy_config, _release, generate_dynamic_workload, run_dynamic,
)
from autoscheduler.evaluation import ALGORITHMS, compare_algorithms, run_algorithm, score_result_against_reference
from autoscheduler.model import PolicyCostModel, load_model
from tools.diagnose_mlfq import run_controlled, trial_action, workload_shape, switch_counterfactual
from simulator.process import Process


class _DeterministicCosts:
    def predict(self, rows):
        active_index = DYNAMIC_FEATURE_NAMES.index("active_policy_index")
        return [[.3, .2, 0., .4, .3] if row[active_index] == 1 else [.3, 0., .2, .4, .3]
                for row in rows]


class MlfqDiagnosticTests(unittest.TestCase):
    def test_finishing_before_dwell_does_not_count_as_an_early_policy_return(self):
        state = _new_state([Process("A",0,4)])
        _release(state,0)
        record = switch_counterfactual({"state":state,"previous":"MLFQ","selected":"Priority",
                                         "time":0,"predicted_costs":[.1,.1,0.,.1,.1]},
                                        compare_algorithms([Process("A",0,4)]))
        self.assertFalse(record["label_switches_back_before_dwell"])

    def test_eligible_counterexample_uses_unchanged_policy_parameters(self):
        processes = [Process(f"P{i}", 0, 60, priority=priority, cpu_bursts=(20,20,20),
                             io_bursts=(100,100)) for i,priority in enumerate((4,1,4))]
        results = compare_algorithms(processes, algorithms=(*ALGORITHMS,"MLFQ"))
        references = {p:results[p] for p in ALGORITHMS}
        self.assertLess(score_result_against_reference(results["FCFS"],references),
                        score_result_against_reference(results["MLFQ"],references))
        self.assertLess(results["FCFS"].avg_turnaround_time,results["MLFQ"].avg_turnaround_time)

    def test_counterfactual_minimum_dwell_is_not_shortened_by_quantum(self):
        state = _new_state([Process("A", 0, 100), Process("B", 0, 100)])
        _release(state,0)
        _, duration = trial_action(state,"MLFQ","Round Robin",20,"MLFQ")
        self.assertGreaterEqual(duration,20)

    def test_constant_mlfq_control_is_exactly_static_mlfq(self):
        for seed in (7, 19, 2026000013):
            workload = generate_dynamic_workload(seed)
            actual, _ = run_controlled(workload.processes, initial="MLFQ", target="MLFQ")
            expected = run_algorithm("MLFQ", workload.processes)
            self.assertEqual(actual.timeline, expected.timeline)
            self.assertEqual(actual.process_metrics, expected.process_metrics)

    def test_saved_schema_two_model_requires_explicit_historical_replay(self):
        path = Path("artifacts/dynamic_v2_20261019/candidates/policy_cost/model.joblib")
        if not path.exists():
            self.skipTest("local frozen cost-model artifact is unavailable")
        with self.assertRaisesRegex(ValueError, "schema|legacy|retrain"):
            load_model(path, DYNAMIC_FEATURE_NAMES)

    def test_cost_model_instrumentation_reproduces_current_router_decisions(self):
        model = PolicyCostModel(_DeterministicCosts(), DYNAMIC_POLICY_NAMES)
        config = DynamicRouterConfig(epoch_ticks=10, dwell_epochs=2)
        for seed in (2026000000, 2026000013, 2026000099):
            workload = generate_dynamic_workload(seed)
            actual, events = run_controlled(workload.processes, config, model=model, initial="Round Robin")
            expected = run_dynamic(workload.processes, model, config)
            self.assertEqual(actual.timeline, expected.simulation.timeline)
            self.assertEqual(actual.process_metrics, expected.simulation.process_metrics)
            self.assertEqual([(r["time"], r["selected"], r["active"], r["accepted"]) for r in events],
                             [(d.time, d.selected, d.active, d.accepted) for d in expected.decisions])
            times = [event["time"] for event in events if event["accepted"]]
            self.assertTrue(all(b-a >= 20 for a,b in zip([0]+times, times)))

    def test_corrected_labels_match_safe_mlfq_continuation_on_fixed_scale(self):
        processes = [Process("A", 0, 25), Process("B", 0, 4)]
        state = _new_state(processes)
        _release(state, 0)
        config = DynamicRouterConfig(epoch_ticks=10, dwell_epochs=2)
        references = compare_algorithms(processes)
        expected_label, expected_scores = _counterfactual_label(
            state, 10, _policy_config(None), config=config, references=references,
        )
        trials = {name: trial_action(state, "Round Robin", name, 20, "MLFQ")[0]
                  for name in DYNAMIC_POLICY_NAMES}
        baseline = score_result_against_reference(trials["MLFQ"], references)
        scores = {name: score_result_against_reference(result, references) - baseline
                  for name, result in trials.items()}
        label = min(DYNAMIC_POLICY_NAMES, key=lambda name: (scores[name], DYNAMIC_POLICY_NAMES.index(name)))
        self.assertEqual(expected_scores, scores)
        self.assertEqual(scores["MLFQ"], 0)
        if scores["Round Robin"] <= scores[label] + 1e-12:
            label = "Round Robin"
        self.assertEqual(expected_label, label)

    def test_shape_describes_all_bursts_and_actual_arrival_span(self):
        shape = workload_shape([Process("A", 0, 6, cpu_bursts=(2,4), io_bursts=(10,)),
                                Process("B", 20, 2)])
        self.assertEqual(shape["process_count"], 2)
        self.assertEqual(shape["arrival_span"], 20)
        self.assertEqual(shape["cpu_burst_count"], 3)
        self.assertEqual(shape["total_cpu"], 8)
        self.assertEqual(shape["total_io"], 10)


if __name__ == "__main__":
    unittest.main()
