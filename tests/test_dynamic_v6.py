"""A longer observed quiet window limits irreversible excursion exposure."""
from dataclasses import replace
import unittest

from autoscheduler.dynamic import DynamicRouterConfig, _tail_action
from tests import test_dynamic_v5 as v5
from autoscheduler.dynamic import run_dynamic, _training_states, extract_dynamic_features
from autoscheduler.evaluation import ALGORITHMS
from simulator.process import Process


class SustainedArrivalTests(unittest.TestCase):
    def config(self):
        return replace(v5.TailProtectionTests().config(), arrival_quiet_dwell_periods=2)

    def test_one_quiet_interval_does_not_establish_safe_departure(self):
        for quiet in (21, 23, 37):
            features = v5.TailProtectionTests().features(arrival_quiet_ticks=quiet)
            self.assertEqual(_tail_action(features, "MLFQ", "Priority", self.config()),
                             ("MLFQ", "arrival_risk"))
            self.assertEqual(_tail_action(features, "MLFQ", "Priority", v5.TailProtectionTests().config()),
                             ("Priority", None))

    def test_stable_batch_departure_and_return_remain_possible(self):
        features = v5.TailProtectionTests().features(arrival_quiet_ticks=40)
        self.assertEqual(_tail_action(features, "MLFQ", "Priority", self.config()), ("Priority", None))
        features["dwell_remaining_ticks"] = 0
        self.assertEqual(_tail_action(features, "Priority", "Priority", self.config()),
                         ("MLFQ", "excursion_expired"))

    def test_runtime_and_training_use_same_admission_constraint(self):
        jobs = [Process(f"P{i}", 0, 30) for i in range(6)] + [Process("late", 33, 2)]
        config = self.config()
        result = run_dynamic(jobs, v5.ExcursionModel(), config)
        states = _training_states(jobs, config, ALGORITHMS["Priority RR"][1], behavior_model=v5.ExcursionModel())
        self.assertEqual([(s.current_time, extract_dynamic_features(s, active, dwell)) for s, active, dwell in states],
                         [(d.time, d.features) for d in result.decisions if not d.features["dwell_remaining_ticks"]])
        self.assertTrue(all(d.time >= 40 for d in result.decisions if d.accepted and d.active != "MLFQ"))

    def test_invalid_window_rejected(self):
        for value in (0, -1, 1.5, True):
            with self.assertRaises(ValueError):
                DynamicRouterConfig(arrival_quiet_dwell_periods=value)

    def test_new_arrivals_are_served_before_later_quiet_departure(self):
        jobs = [Process(f"P{i}", 0, 30) for i in range(6)] + [Process("late", 33, 2)]
        old = run_dynamic(jobs, v5.ExcursionModel(), v5.TailProtectionTests().config())
        new = run_dynamic(jobs, v5.ExcursionModel(), self.config())
        response = lambda result: next(m.response_time for m in result.simulation.process_metrics if m.pid == "late")
        self.assertLess(response(new), response(old))
        self.assertTrue(any(d.accepted and d.active == "FCFS" for d in new.decisions))

    def test_artifact_configuration_cannot_silently_change_to_new_guard(self):
        model = v5.ExcursionModel()
        model.dynamic_config_ = v5.TailProtectionTests().config().__dict__
        with self.assertRaisesRegex(ValueError, "configuration differs"):
            run_dynamic([Process("a", 0, 100)], model, self.config())

    def test_existing_safety_contract_with_longer_window(self):
        for check in (
            v5.TailProtectionTests.test_nonzero_context_switch_overhead_and_late_arrivals_conserve_service,
            v5.TailProtectionTests.test_no_switch_cannot_renew_excursion_after_first_legal_review,
            v5.TailProtectionTests.test_missing_model_fallback_keeps_minimum_dwell,
            v5.TailProtectionTests.test_quiet_feature_uses_released_arrivals_only,
        ):
            with self.subTest(check=check.__name__):
                check(self)


if __name__ == "__main__":
    unittest.main()
