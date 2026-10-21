"""Response-tail safeguards act on observed state at legal review boundaries."""

import copy
from collections import Counter
from pathlib import Path
import tempfile
import unittest

from autoscheduler.dynamic import (
    DYNAMIC_FEATURE_NAMES, DynamicRouterConfig, _new_state, _dispatch,
    _training_states, extract_dynamic_features, run_dynamic,
)
from autoscheduler.evaluation import ALGORITHMS
from simulator.process import Process


class ExcursionModel:
    def __init__(self, policy="FCFS"):
        self.policy = policy

    def predict(self, rows):
        index = DYNAMIC_FEATURE_NAMES.index("active_policy_index")
        return [self.policy if row[index] == 4 else "No Switch" for row in rows]


class TailProtectionTests(unittest.TestCase):
    def config(self, **kwargs):
        return DynamicRouterConfig(epoch_ticks=10, dwell_epochs=2, initial_policy="MLFQ",
            fallback_policy="MLFQ", explicit_no_switch=True, response_tail_protection=True,
            mlfq_quanta=(1, 2, 4), mlfq_aging_threshold=40, **kwargs)

    def features(self, **updates):
        features = dict.fromkeys(DYNAMIC_FEATURE_NAMES, 0.)
        features.update(ready_count=5., arrival_quiet_ticks=100., ready_wait_p95=5.)
        features.update(updates)
        return features

    def test_multiple_unserved_jobs_approaching_long_wait_request_return(self):
        from autoscheduler.dynamic import _tail_action
        selected, reason = _tail_action(self.features(first_service_ready_count=3,
            first_service_wait_max=18, ready_wait_p95=22, dwell_remaining_ticks=5),
            "FCFS", "FCFS", self.config())
        self.assertEqual(selected, "MLFQ")
        self.assertEqual(reason, "first_response_return")

    def test_new_arrival_burst_blocks_departure_without_reading_future(self):
        from autoscheduler.dynamic import _tail_action
        selected, reason = _tail_action(self.features(arrival_quiet_ticks=2, recent_arrivals=6),
                                        "MLFQ", "Priority", self.config())
        self.assertEqual((selected, reason), ("MLFQ", "arrival_risk"))

    def test_quiet_low_pressure_switch_remains_possible(self):
        from autoscheduler.dynamic import _tail_action
        self.assertEqual(_tail_action(self.features(), "MLFQ", "FCFS", self.config()), ("FCFS", None))

    def test_io_returns_with_competing_waiters_block_only_during_pressure(self):
        jobs = [Process("I", 0, 4, cpu_bursts=(1, 1, 1, 1), io_bursts=(9, 4, 9))]
        jobs += [Process(f"P{i:02}", 0, 30) for i in range(15)]
        result = run_dynamic(jobs, ExcursionModel(), self.config())
        risky = [d for d in result.decisions if d.reason == "io_ready_pressure"]
        self.assertTrue(risky)
        self.assertTrue(all(d.features["io_returns"] > 0 and d.features["ready_count"] > 1 for d in risky))
        self.assertTrue(any(d.accepted and d.active == "FCFS" for d in result.decisions))

    def test_no_switch_cannot_renew_excursion_after_first_legal_review(self):
        jobs = [Process(f"P{i}", 0, 30) for i in range(6)] + [Process("late", 33, 2)]
        result = run_dynamic(jobs, ExcursionModel(), self.config())
        last_switch = 0
        previous = "MLFQ"
        boundaries = {end for _, _, end in result.simulation.timeline}
        expired = []
        for d in result.decisions:
            if previous != "MLFQ" and d.time >= last_switch + 20:
                self.assertTrue(d.accepted)
                self.assertEqual(d.active, "MLFQ")
                expired.append(d)
            if d.accepted:
                self.assertGreaterEqual(d.time - last_switch, 20)
                self.assertIn(d.time, boundaries)
                previous, last_switch = d.active, d.time
        self.assertTrue(expired)

    def test_missing_model_fallback_keeps_minimum_dwell(self):
        from dataclasses import replace
        config = replace(self.config(), initial_policy="Round Robin")
        result = run_dynamic([Process("a", 0, 100), Process("b", 0, 100)], None, config)
        accepted = [d for d in result.decisions if d.accepted]
        self.assertTrue(accepted)
        self.assertEqual(accepted[0].time, 20)
        self.assertEqual(accepted[0].active, "MLFQ")

    def test_nonzero_context_switch_overhead_and_late_arrivals_conserve_service(self):
        jobs = [Process(f"P{i}", 0, 30) for i in range(6)] + [Process("late", 37, 2)]
        result = run_dynamic(jobs, ExcursionModel("Priority RR"), self.config())
        timeline = result.simulation.timeline
        self.assertTrue(all(b > a for _, a, b in timeline))
        self.assertGreater(result.simulation.context_switch_time, 0)
        service = Counter()
        for pid, a, b in timeline:
            if pid != "CS":
                service[pid] += b - a
            else:
                self.assertEqual(b - a, 1)
        self.assertEqual(service, Counter({p.pid: p.burst_time for p in jobs}))

    def test_quiet_feature_uses_released_arrivals_only(self):
        state = _new_state([Process("a", 0, 100), Process("future", 100, 30)], self.config())
        _dispatch(state, "MLFQ", ALGORITHMS["Priority RR"][1])
        other = copy.deepcopy(state)
        other.pending[0].arrival_time = 999
        other.pending[0].burst_time = 999
        self.assertEqual(extract_dynamic_features(state), extract_dynamic_features(other))
        self.assertEqual(extract_dynamic_features(state)["arrival_quiet_ticks"], 1)

    def test_training_and_runtime_actionable_states_match(self):
        config = self.config()
        jobs = [Process(f"P{i}", 0, 30) for i in range(6)] + [Process("late", 33, 2)]
        model = ExcursionModel()
        result = run_dynamic(jobs, model, config)
        states = _training_states(jobs, config, ALGORITHMS["Priority RR"][1], behavior_model=model)
        self.assertEqual([(s.current_time, extract_dynamic_features(s, active, dwell)) for s, active, dwell in states],
                         [(d.time, d.features) for d in result.decisions if not d.features["dwell_remaining_ticks"]])

    def test_no_unsafe_family_can_be_selected(self):
        from autoscheduler.model import select_eligible_family
        unsafe = {"classifier": {"validation_schedule_eligible": False, "validation_schedule_score": .1}}
        self.assertIsNone(select_eligible_family(unsafe))
        unsafe["cost"] = {"validation_schedule_eligible": True, "validation_schedule_score": .2}
        self.assertEqual(select_eligible_family(unsafe), "cost")

    def test_tail_horizon_cannot_silently_exceed_actual_excursion(self):
        with self.assertRaisesRegex(ValueError, "horizon"):
            self.config(label_horizon_ticks=30)
        with self.assertRaisesRegex(ValueError, "first-service"):
            self.config(first_service_protection=False)

    def test_audit_pairing_uses_unique_workload_identity(self):
        from autoscheduler.dynamic_v5_experiment import paired
        rows = [{"seed": seed, **dict.fromkeys(("score", "p95_response", "worst_response", "starvation", "switches"), float(seed))}
                for seed in (1, 2)]
        intervals = paired(rows, list(reversed(rows)))
        self.assertTrue(all(interval["mean"] == interval["ci_low"] == interval["ci_high"] == 0
                            for interval in intervals.values()))
        with self.assertRaises(ValueError):
            paired(rows, [rows[0]])

    def test_original_strict_latency_gate_and_primary_response_boundary_remain(self):
        from autoscheduler.dynamic_v5_experiment import acceptance
        primary = {"score_difference": {"ci_high": -.01}, "p95_response_difference": {"ci_high": 0},
                   "starvation_difference": {"mean": 0}}
        rr = {"score_difference": {"ci_high": 0}, "p95_response_difference": {"ci_high": -.01}}
        self.assertTrue(all(acceptance((primary, rr), 9.999).values()))
        self.assertFalse(acceptance((primary, rr), 10)["latency"])

    def test_failed_training_gates_mark_saved_model_diagnostic_only(self):
        from autoscheduler.dynamic import dynamic_action_names
        from autoscheduler.model import train_model
        config = self.config()
        rows = []
        for seed in range(8):
            for epoch in range(4):
                row = dict.fromkeys(DYNAMIC_FEATURE_NAMES, 0.)
                row.update(seed=seed, epoch=epoch, label="No Switch")
                row.update({"score_" + action.lower().replace(" ", "_"): 0. for action in dynamic_action_names(config)})
                rows.append(row)
        with tempfile.TemporaryDirectory() as directory:
            report = train_model(rows, Path(directory) / "diagnostic.joblib", feature_names=DYNAMIC_FEATURE_NAMES,
                metadata={"dynamic_config": config.__dict__, "static_baseline": "MLFQ"},
                candidate_settings=[(3, 10, None)], refit=False,
                scheduler_validation=lambda model: {"validation_schedule_eligible": False, "validation_schedule_score": .1})
        self.assertFalse(report["selected_for_development"])
        self.assertTrue(report["diagnostic_only"])


if __name__ == "__main__":
    unittest.main()
