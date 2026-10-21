"""Presentation routing must call original v5, never an experimental wrapper."""
from dataclasses import asdict
import unittest


class FacultyDashboardTests(unittest.TestCase):
    def test_only_original_v5_is_a_dynamic_simulation_option(self):
        from dashboard.adapter import catalog
        options=catalog()['algorithms']
        self.assertEqual([n for n in options if n.startswith('Dynamic')],['Dynamic ML (v5)'])

    def test_v5_playback_matches_direct_original_model_and_records_real_events(self):
        from dashboard.adapter import simulation,processes,ROOT
        from autoscheduler.dynamic import DYNAMIC_FEATURE_NAMES,DynamicRouterConfig,run_dynamic
        from autoscheduler.model import load_model,load_model_metadata
        path=ROOT/'artifacts/dynamic_v5_20261019/policy_cost/model.joblib'
        config=DynamicRouterConfig(**load_model_metadata(path)['dynamic_config'])
        expected=run_dynamic(processes('mixed_io'),load_model(path,DYNAMIC_FEATURE_NAMES,expected_dynamic_config=config),config)
        actual=simulation('mixed_io','Dynamic ML (v5)')
        self.assertEqual(actual['timeline'],expected.simulation.timeline)
        self.assertEqual(actual['processes'],[asdict(p) for p in expected.simulation.process_metrics])
        fields=lambda d:(d['time'],d['selected'],d['active'],d['accepted'],d['reason'])
        self.assertEqual([fields(d) for d in actual['routing_decisions']],[fields(asdict(d)) for d in expected.decisions])
        self.assertEqual(actual['dynamic_model']['version'],'v5')
        self.assertEqual(actual['frames'][-1]['completed'],len(actual['processes']))

    def test_api_rejects_other_dynamic_variants(self):
        from fastapi.testclient import TestClient
        from dashboard.app import app
        with TestClient(app) as client:
            for name in ['Dynamic ML (v6)','Azure tree','Guard candidate']:
                self.assertEqual(client.get('/api/simulation',params={'algorithm':name}).status_code,404)
            self.assertEqual(client.get('/api/simulation',params={'algorithm':'Dynamic ML (v5)'}).status_code,200)


if __name__=='__main__':unittest.main()
