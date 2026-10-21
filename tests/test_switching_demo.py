"""One experimental-demo API reproduction and playback consistency check."""
import unittest


class SwitchingDemoTests(unittest.TestCase):
    def test_fitted_demo_transitions_match_api_and_every_playback_tick(self):
        from fastapi.testclient import TestClient
        from dashboard.app import app
        from dashboard.adapter import _multi_demo,processes,catalog
        from autoscheduler.dynamic import run_dynamic
        with TestClient(app) as client:
            response=client.get('/api/simulation',params={'workload':'dynamic_multi_policy','algorithm':'Dynamic ML (v5)'})
            self.assertEqual(response.status_code,200)
            data=response.json()
        model,config=_multi_demo()
        expected=run_dynamic(processes('dynamic_multi_policy'),model,config)
        self.assertEqual(data['timeline'],[list(t) for t in expected.simulation.timeline])
        events=data['policy_transitions']
        self.assertEqual([(e['decision_tick'],e['from_policy'],e['to_policy'],e['reason']) for e in events],
            [(22,'MLFQ','Priority','accepted'),(49,'Priority','MLFQ','excursion_expired'),
             (70,'MLFQ','FCFS','accepted'),(94,'FCFS','MLFQ','excursion_expired'),
             (122,'MLFQ','FCFS','accepted'),(156,'FCFS','MLFQ','excursion_expired'),(180,'MLFQ','Priority','accepted')])
        self.assertEqual([(d.time,d.active) for d in expected.decisions if d.accepted],[(e['effective_tick'],e['to_policy']) for e in events])
        self.assertTrue(all(e['decision_tick']==e['effective_tick'] for e in events))
        self.assertEqual(data['reproducibility']['workload_id'],'dynamic_multi_policy')
        self.assertEqual(len(data['reproducibility']['input_processes']),7)
        self.assertEqual(data['dynamic_model']['version'],'experimental_demo')
        self.assertIn('not original fitted v5',data['dynamic_model']['label'])
        self.assertEqual(config.__dict__,data['dynamic_model']['configuration']|{'mlfq_quanta':tuple(data['dynamic_model']['configuration']['mlfq_quanta'])})
        for frame in data['frames']:
            past=[e for e in events if e['effective_tick']<=frame['tick']]
            self.assertEqual(frame['active_policy'],past[-1]['to_policy'] if past else 'MLFQ')
        self.assertEqual({p['policy'] for p in data['policy_timeline']},{'MLFQ','Priority','FCFS'})
        for period in data['policy_timeline']:
            self.assertTrue(any(start<period['end'] and end>period['start'] for _,start,end in data['timeline']))
        for d in data['routing_decisions']:
            for action,cost in d['predicted_costs'].items():
                self.assertAlmostEqual(d['predicted_policy_benefits'][action],d['predicted_costs']['No Switch']-cost)
        ids=[w['id'] for w in catalog()['workloads']]
        self.assertNotIn('dynamic_hold',ids);self.assertNotIn('dynamic_switching',ids)
