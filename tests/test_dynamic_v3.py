"""Independent-clock regressions for the versioned dynamic scheduling contract."""

from collections import Counter
import copy
from pathlib import Path
import tempfile
import unittest

from autoscheduler.dynamic import (
    DYNAMIC_FEATURE_NAMES, DYNAMIC_POLICY_NAMES, DYNAMIC_SCHEMA_VERSION,
    DynamicRouterConfig, _counterfactual_label, _dispatch, _new_state, _release,
    _run_to_completion, _simulation, _switch_policy, dynamic_policy_parameters,
    extract_dynamic_features, generate_dynamic_workload, run_dynamic,
)
from autoscheduler.evaluation import ALGORITHMS, compare_algorithms, score_result_against_reference
from scheduler.mlfq import mlfq
from simulator.process import Process
from simulator.simulator import run_simulation


class DynamicV3AccountingTests(unittest.TestCase):
    def test_observed_ready_wait_survives_mlfq_aging_promotion(self):
        processes = [Process("A", 0, 3)]
        processes.extend(Process(f"P{tick}", tick, 1) for tick in range(1, 22))
        processes.append(Process("P23", 23, 1))
        state = _new_state(processes)
        while state.current_time < 23:
            _dispatch(state, "MLFQ", ALGORITHMS["Priority RR"][1])
        self.assertEqual(state.current_time, 23)
        self.assertEqual([entry for entry in state.timeline if entry[0] == "A"], [("A", 0, 2)])
        # A has remained continuously ready since tick 2. Its aging promotion
        # at tick 22 must not erase the twenty ticks already spent waiting.
        features = extract_dynamic_features(state, "MLFQ")
        self.assertEqual(features["ready_wait_max"], 21)
        self.assertEqual(features["ready_wait_mean"], 10.5)

    def test_mlfq_reselects_top_queue_arrival_at_switch_overhead_boundary(self):
        processes = [Process("A", 0, 10), Process("B", 0, 1), Process("C", 5, 1)]
        result = run_simulation("MLFQ", mlfq, processes, context_switch_cost=1)
        # A is demoted after [0,2]. B finishes at 4. C arrives at tick 5,
        # exactly when the next switch completes, and outranks demoted A.
        self.assertEqual(result.timeline, [
            ("A", 0, 2), ("CS", 2, 3), ("B", 3, 4), ("CS", 4, 5),
            ("C", 5, 6), ("CS", 6, 7), ("A", 7, 11), ("A", 11, 15),
        ])
        self.assertEqual(result.context_switch_time, 3)
        self.assertEqual(result.makespan, 15)

    def test_nonzero_cost_mlfq_never_records_zero_service_dispatch(self):
        workload = generate_dynamic_workload(2026000013)
        result = run_simulation("MLFQ", mlfq, list(workload.processes), context_switch_cost=1)
        self.assertTrue(all(end > start for _, start, end in result.timeline))
        service = Counter()
        for pid, start, end in result.timeline:
            if pid != "CS":
                service[pid] += end - start
        self.assertEqual(service, Counter({process.pid: process.burst_time for process in workload.processes}))

    def test_existing_arrival_preemption_fixture_keeps_positive_intervals(self):
        result = run_simulation("MLFQ", mlfq, [Process("A", 0, 10), Process("B", 3, 1)],
                                context_switch_cost=1)
        self.assertTrue(all(end > start for _, start, end in result.timeline))
        self.assertEqual(sum(end - start for pid, start, end in result.timeline if pid != "CS"), 11)

    def test_active_feature_semantics_require_current_schema(self):
        self.assertEqual(DYNAMIC_SCHEMA_VERSION, 5)


class _NeverAskedModel:
    def predict(self, rows):
        raise AssertionError("no review is due during this workload")


class _UncertainModel:
    classes_ = DYNAMIC_POLICY_NAMES

    def predict(self, rows):
        return ["FCFS"] * len(rows)

    def predict_proba(self, rows):
        return [[0.2] * len(self.classes_) for _ in rows]


class _MarginRejectedModel:
    def predict(self, rows):
        return ["FCFS"] * len(rows)

    def switch_allowed(self, features, active, selected):
        return False


class DynamicV3StartupTests(unittest.TestCase):
    def test_mlfq_startup_matches_static_mlfq_before_first_review(self):
        processes = [
            Process("A", 0, 10), Process("B", 3, 1),
            Process("C", 0, 4, cpu_bursts=(1, 3), io_bursts=(3,)),
        ]
        config = DynamicRouterConfig(epoch_ticks=10000, initial_policy="MLFQ", fallback_policy="MLFQ")
        actual = run_dynamic(processes, _NeverAskedModel(), config)
        expected = run_simulation("MLFQ", mlfq, processes)
        self.assertEqual(actual.initial_policy, "MLFQ")
        self.assertEqual(actual.final_policy, "MLFQ")
        self.assertEqual(actual.decisions, [])
        self.assertEqual(actual.simulation.timeline, expected.timeline)
        self.assertEqual(actual.simulation.process_metrics, expected.process_metrics)

    def test_historical_default_startup_and_hold_current_fallback_are_explicit(self):
        config = DynamicRouterConfig()
        self.assertEqual(config.initial_policy, "Round Robin")
        self.assertIsNone(config.fallback_policy)

    def test_realistic_startup_and_fallback_reject_oracle_policies(self):
        for kwargs in ({"initial_policy": "SJF"}, {"fallback_policy": "SRTF"},
                       {"initial_policy": "unknown"}, {"fallback_policy": "unknown"}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    DynamicRouterConfig(**kwargs)

    def test_missing_model_falls_back_at_safe_review_after_dwell(self):
        config = DynamicRouterConfig(epoch_ticks=10, dwell_epochs=2, fallback_policy="MLFQ")
        result = run_dynamic([Process("A", 0, 100), Process("B", 0, 100)], None, config)
        accepted = [decision for decision in result.decisions if decision.accepted]
        self.assertTrue(accepted)
        self.assertEqual(accepted[0].time, 20)
        self.assertEqual(accepted[0].active, "MLFQ")
        self.assertTrue(all(decision.active == "Round Robin" for decision in result.decisions if decision.time < 20))
        boundaries = {end for _, _, end in result.simulation.timeline}
        self.assertTrue(all(decision.time in boundaries for decision in accepted))

    def test_low_classifier_confidence_uses_configured_fallback_after_dwell(self):
        config = DynamicRouterConfig(epoch_ticks=10, dwell_epochs=2, fallback_policy="MLFQ")
        result = run_dynamic([Process("A", 0, 100), Process("B", 0, 100)], _UncertainModel(), config)
        accepted = [decision for decision in result.decisions if decision.accepted]
        self.assertTrue(accepted)
        self.assertEqual((accepted[0].time, accepted[0].active), (20, "MLFQ"))

    def test_cost_margin_rejection_keeps_current_policy_instead_of_fallback(self):
        config = DynamicRouterConfig(epoch_ticks=10, fallback_policy="MLFQ")
        result = run_dynamic([Process("A", 0, 100), Process("B", 0, 100)], _MarginRejectedModel(), config)
        self.assertTrue(result.decisions)
        self.assertFalse(any(decision.accepted for decision in result.decisions))
        self.assertEqual(result.final_policy, "Round Robin")


class DynamicV3LabelTests(unittest.TestCase):
    def test_label_rechecks_review_deadline_after_idle_before_dispatching_late_jobs(self):
        processes = [Process("A", 0, 1), Process("B", 100, 10), Process("C", 101, 1)]
        state = _new_state(processes)
        _release(state, 0)
        config = DynamicRouterConfig(epoch_ticks=10, dwell_epochs=2)
        rr_config = ALGORITHMS["Priority RR"][1]
        references = compare_algorithms(processes)
        _, costs = _counterfactual_label(state, 10, rr_config, config=config, references=references)
        trial = copy.deepcopy(state)
        while trial.pending or trial.ready or trial.blocked:
            _release(trial, trial.current_time)
            if not trial.ready:
                next_events = [p.arrival_time for p in trial.pending] + [time for time, *_ in trial.blocked]
                if not next_events:
                    break
                trial.current_time = min(next_events)
                _release(trial, trial.current_time)
            # Review the now-ready state at tick 100 before running B. FCFS
            # was authorized through the first legal review after tick 20.
            if trial.current_time >= 20:
                break
            _dispatch(trial, "FCFS", rr_config)
        self.assertEqual(trial.current_time, 100)
        self.assertEqual(trial.timeline, [("A", 0, 1)])
        _switch_policy(trial, "FCFS", "MLFQ")
        _run_to_completion(trial, "MLFQ", rr_config)
        self.assertIn(("B", 100, 102), trial.timeline)
        self.assertAlmostEqual(costs["FCFS"], costs["MLFQ"])
        baseline = run_simulation("MLFQ", mlfq, processes)
        expected = score_result_against_reference(_simulation(trial, "FCFS"), references)
        expected -= score_result_against_reference(baseline, references)
        self.assertAlmostEqual(costs["FCFS"], expected)

    def test_explicit_label_horizon_cannot_violate_minimum_dwell(self):
        with self.assertRaisesRegex(ValueError, "horizon|dwell"):
            DynamicRouterConfig(epoch_ticks=10, dwell_epochs=2, label_horizon_ticks=10)

    def test_dwell_blocked_states_are_not_labeled_as_actionable_alternatives(self):
        processes = [Process("A", 0, 30), Process("B", 0, 20)]
        state = _new_state(processes)
        _release(state, 0)
        config = DynamicRouterConfig(epoch_ticks=10, dwell_epochs=2)
        with self.assertRaisesRegex(ValueError, "dwell"):
            _counterfactual_label(state, 10, ALGORITHMS["Priority RR"][1],
                                  dwell_remaining_ticks=10, config=config,
                                  references=compare_algorithms(processes))

    def test_label_cost_differences_use_safe_horizon_mlfq_tail_and_fixed_bounds(self):
        processes = [Process("A", 0, 30, priority=2), Process("B", 0, 20, priority=1),
                     Process("C", 8, 5, priority=3)]
        config = DynamicRouterConfig(epoch_ticks=10, dwell_epochs=2)
        references = compare_algorithms(processes)
        state = _new_state(processes)
        _release(state, 0)
        _, costs = _counterfactual_label(state, 10, ALGORITHMS["Priority RR"][1],
                                        config=config, references=references)
        self.assertAlmostEqual(costs["MLFQ"], 0.0)
        expected = {}
        for policy in ("FCFS", "Round Robin"):
            trial = copy.deepcopy(state)
            _switch_policy(trial, "Round Robin", policy)
            while (trial.pending or trial.ready or trial.blocked) and trial.current_time < 20:
                _dispatch(trial, policy, ALGORITHMS["Priority RR"][1])
            _switch_policy(trial, policy, "MLFQ")
            _run_to_completion(trial, "MLFQ", ALGORITHMS["Priority RR"][1])
            expected[policy] = score_result_against_reference(_simulation(trial, policy), references)
        self.assertAlmostEqual(costs["Round Robin"] - costs["FCFS"],
                               expected["Round Robin"] - expected["FCFS"])

    def test_off_grid_labels_wait_for_next_legal_review_after_dwell_expiry(self):
        processes = [Process("warmup", 0, 13), Process("A", 13, 100), Process("B", 13, 100)]
        state = _new_state(processes)
        rr_config = ALGORITHMS["Priority RR"][1]
        while state.current_time < 13:
            _dispatch(state, "Round Robin", rr_config)
        self.assertEqual(state.current_time, 13)
        config = DynamicRouterConfig(epoch_ticks=10, dwell_epochs=2)
        references = compare_algorithms(processes)
        _, costs = _counterfactual_label(state, 10, rr_config, config=config, references=references)
        expected = {}
        for policy in ("FCFS", "Round Robin"):
            trial = copy.deepcopy(state)
            _switch_policy(trial, "Round Robin", policy)
            # A switch at 13 expires at 33; global reviews are 10,20,30,40.
            # Its first eligible review is 40, then the next dispatch boundary.
            while (trial.pending or trial.ready or trial.blocked) and trial.current_time < 40:
                _dispatch(trial, policy, rr_config)
            if policy == "Round Robin":
                self.assertEqual(trial.current_time, 41)
            _switch_policy(trial, policy, "MLFQ")
            _run_to_completion(trial, "MLFQ", rr_config)
            expected[policy] = score_result_against_reference(_simulation(trial, policy), references)
        self.assertAlmostEqual(costs["Round Robin"] - costs["FCFS"],
                               expected["Round Robin"] - expected["FCFS"])


class _StoredModel:
    classes_ = ("MLFQ",)
    n_features_in_ = len(DYNAMIC_FEATURE_NAMES)

    def predict(self, rows):
        return ["MLFQ"] * len(rows)


class DynamicV3PersistenceTests(unittest.TestCase):
    def _load_bundle(self, version):
        import joblib
        from autoscheduler.model import load_model

        config = DynamicRouterConfig()
        rr_config = dict(ALGORITHMS["Priority RR"][1])
        bundle = {
            "model": _StoredModel(), "features": DYNAMIC_FEATURE_NAMES,
            "metadata": {
                "schema_version": version, "model_kind": "classifier",
                "dynamic_config": config.__dict__, "policy_set": list(DYNAMIC_POLICY_NAMES),
                "priority_rr_config": rr_config,
                "policy_parameters": dynamic_policy_parameters(config, rr_config),
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidate.joblib"
            joblib.dump(bundle, path)
            return load_model(path, DYNAMIC_FEATURE_NAMES)

    def test_current_bundle_positive_control_loads(self):
        model = self._load_bundle(DYNAMIC_SCHEMA_VERSION)
        self.assertEqual(model.predict([[0.0] * len(DYNAMIC_FEATURE_NAMES)]), ["MLFQ"])

    def test_schema_two_bundle_cannot_use_corrected_feature_semantics(self):
        with self.assertRaises(ValueError):
            self._load_bundle(2)


class DynamicV3AuditMetricTests(unittest.TestCase):
    def test_audit_unavailable_model_with_mlfq_fallback_is_continuous_mlfq(self):
        from autoscheduler.dynamic_training import prepare_validation
        from autoscheduler.dynamic_v3_experiment import audit_cases

        config = DynamicRouterConfig(epoch_ticks=10, dwell_epochs=2,
                                     initial_policy="MLFQ", fallback_policy="MLFQ")
        cases, _ = prepare_validation(2, 998, config)
        tuned = {"quanta": (2, 4, 8), "aging_threshold": 20, "context_switch_cost": 0}
        rows, summaries = audit_cases(cases, {"MLFQ fallback": None}, config, tuned)
        by_key = {(row["seed"], row["policy"]): row for row in rows}
        for workload, _, _ in cases:
            actual = by_key[workload.seed, "MLFQ fallback"]
            baseline = by_key[workload.seed, "MLFQ"]
            for metric in ("score", "p95_response", "starvation"):
                self.assertEqual(actual[metric], baseline[metric])
            self.assertEqual(actual["switches"], 0)
        comparison = summaries["MLFQ fallback"]["comparisons"]["MLFQ"]
        for metric in ("score", "p95_response", "starvation"):
            self.assertEqual(comparison[metric + "_difference"], {"mean": 0.0, "ci_low": 0.0, "ci_high": 0.0})
        self.assertEqual((comparison["wins"], comparison["ties"], comparison["losses"]), (0, 2, 0))

    def test_audit_static_api_and_workload_paired_confidence_intervals(self):
        from autoscheduler.dynamic_training import prepare_validation
        from autoscheduler.dynamic_v3_experiment import audit_cases
        from autoscheduler.experiments import paired_bootstrap_ci

        config = DynamicRouterConfig(epoch_ticks=10000)
        cases, _ = prepare_validation(2, 997, config)
        cases.reverse()
        tuned = {"quanta": (2, 4, 8), "aging_threshold": 20, "context_switch_cost": 0}
        rows, summaries = audit_cases(cases, {"RR control": _NeverAskedModel()}, config, tuned)
        by_key = {(row["seed"], row["policy"]): row for row in rows}
        for workload, _, references in cases:
            seed = workload.seed
            self.assertEqual(by_key[seed, "MLFQ"]["score"], by_key[seed, "Tuned MLFQ"]["score"])
            self.assertEqual(by_key[seed, "RR control"]["score"], by_key[seed, "Round Robin"]["score"])
            expected = run_simulation("MLFQ", mlfq, list(workload.processes), **tuned)
            self.assertEqual(by_key[seed, "Tuned MLFQ"]["score"],
                             score_result_against_reference(expected, references))
        differences = [by_key[workload.seed, "RR control"]["score"] - by_key[workload.seed, "MLFQ"]["score"]
                       for workload, _, _ in cases]
        self.assertEqual(summaries["RR control"]["comparisons"]["MLFQ"]["score_difference"],
                         paired_bootstrap_ci(differences))
        self.assertEqual(summaries["RR control"]["comparisons"]["Round Robin"]["score_difference"],
                         {"mean": 0.0, "ci_low": 0.0, "ci_high": 0.0})


class DynamicV3CliTests(unittest.TestCase):
    def test_dynamic_training_cli_keeps_historical_startup_defaults(self):
        from autoscheduler.cli import build_parser

        arguments = build_parser().parse_args(["dynamic-train"])
        self.assertEqual(arguments.initial_policy, "Round Robin")
        self.assertEqual(arguments.fallback_policy, "hold")

    def test_dynamic_training_cli_accepts_explicit_development_mlfq_startup(self):
        from autoscheduler.cli import build_parser

        arguments = build_parser().parse_args([
            "dynamic-train", "--initial-policy", "MLFQ", "--fallback-policy", "MLFQ",
            "--workload-suite", "development",
        ])
        self.assertEqual(arguments.initial_policy, "MLFQ")
        self.assertEqual(arguments.fallback_policy, "MLFQ")
        self.assertEqual(arguments.workload_suite, "development")


if __name__ == "__main__":
    unittest.main()
