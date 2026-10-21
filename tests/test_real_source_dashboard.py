"""Focused external-evidence and isolated admission-guard checks."""
import unittest
import json
from pathlib import Path


class RealSourceReviewTests(unittest.TestCase):
    def test_guard_vetoes_only_unbounded_nonpreemptive_actions(self):
        from autoscheduler.real_source_review import NonPreemptiveAdmissionGuard
        class Model:
            def predict(self, matrix):
                return ['FCFS', 'Priority', 'Round Robin', 'Priority RR', 'MLFQ', 'No Switch']
        guard = NonPreemptiveAdmissionGuard(Model())
        self.assertEqual(guard.predict([[0]] * 6),
                         ['No Switch', 'No Switch', 'Round Robin', 'Priority RR', 'MLFQ', 'No Switch'])
        self.assertEqual(guard.veto_count, 2)

    def test_guard_preserves_features_and_switch_margin(self):
        from autoscheduler.real_source_review import NonPreemptiveAdmissionGuard
        class Model:
            def switch_allowed(self, features, active, selected):
                return features == {'ready_count': 2} and active == 'MLFQ' and selected == 'Round Robin'
        guard = NonPreemptiveAdmissionGuard(Model())
        features = {'ready_count': 2}
        self.assertTrue(guard.switch_allowed(features, 'MLFQ', 'Round Robin'))
        self.assertFalse(guard.switch_allowed(features, 'MLFQ', 'MLFQ'))
        self.assertEqual(features, {'ready_count': 2})

    def test_catalog_has_separate_real_source_evidence(self):
        from dashboard.adapter import catalog
        self.assertIn('real_source_dynamic', catalog().keys())

    @unittest.skipUnless(Path('results/real_source_dynamic_review_20261020/dashboard.json').exists(), 'saved external review unavailable')
    def test_api_preserves_real_source_provenance_and_failed_gates(self):
        from fastapi.testclient import TestClient
        from dashboard.app import app
        source = json.loads(Path('results/dynamic_azure_generalization/summary.json').read_text())
        with TestClient(app) as client:
            response = client.get('/api/catalog')
        self.assertEqual(response.status_code, 200)
        result = response.json()['real_source_dynamic']
        self.assertFalse(result['genuine_scheduler_events'])
        self.assertFalse(result['training']['occurred'])
        self.assertTrue(all(s['mae'] is None and s['rmse'] is None and s['r_squared'] is None for s in result['training']['splits'].values()))
        self.assertEqual(result['external']['metrics']['Dynamic v5'], source['policy_summary']['Dynamic v5']['common_complete_means'])
        self.assertEqual(result['external']['timeouts'], len(source['timeouts']))
        self.assertFalse(result['external']['improved_over_tuned_mlfq'])
        self.assertFalse(result['candidate']['promoted'])


if __name__ == '__main__':
    unittest.main()
