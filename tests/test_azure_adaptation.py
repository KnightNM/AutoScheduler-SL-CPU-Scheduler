"""Sampling, safe action eligibility and the known nonpreemptive failure."""
import unittest
import json
from pathlib import Path
from autoscheduler.dynamic import DynamicRouterConfig, _training_states, run_dynamic
from autoscheduler.evaluation import ALGORITHMS
from simulator.process import Process


class AzureAdaptationTests(unittest.TestCase):
    def config(self):
        return DynamicRouterConfig(epoch_ticks=10, dwell_epochs=2, initial_policy='MLFQ',
            fallback_policy='MLFQ', explicit_no_switch=True, response_tail_protection=True,
            mlfq_quanta=(1,2,4), mlfq_aging_threshold=40)

    def test_bounded_reservoir_preserves_real_states_and_determinism(self):
        jobs=[Process('A',0,100),Process('B',30,20)]
        rr=ALGORITHMS['Priority RR'][1]
        full=_training_states(jobs,self.config(),rr,'MLFQ',123)
        sampled=_training_states(jobs,self.config(),rr,'MLFQ',123,max_states=3)
        again=_training_states(jobs,self.config(),rr,'MLFQ',123,max_states=3)
        self.assertEqual(sampled,again)
        self.assertEqual(len(sampled),3)
        self.assertTrue(all(any(s==original for original in full) for s in sampled))

    def test_restricted_cost_actions_prevent_old_priority_response_failure(self):
        from autoscheduler.azure_adaptation import ACTIONS
        from autoscheduler.model import PolicyCostModel
        class Priority:
            def predict(self,rows):return ['Priority']*len(rows)
        class Costs:
            def predict(self,rows):return [[0,0,-.1,.1] for _ in rows]
        jobs=[Process('long',0,100),Process('late',40,2)]
        old=run_dynamic(jobs,Priority(),self.config())
        new=run_dynamic(jobs,PolicyCostModel(Costs(),ACTIONS),self.config())
        response=lambda r:next(p.response_time for p in r.simulation.process_metrics if p.pid=='late')
        self.assertEqual(response(old),60)
        self.assertLessEqual(response(new),2)
        self.assertFalse(any(d.accepted and d.active in {'FCFS','Priority'} for d in new.decisions))

    @unittest.skipUnless(Path('results/azure_adapted_20261020/results.json').exists(),'local experiment unavailable')
    def test_saved_experiment_has_disjoint_provenance_and_no_holdout_access(self):
        p=json.loads(Path('results/azure_adapted_20261020/protocol.json').read_text())
        groups={s:{w['source_group'] for w in p['selected'] if w['split']==s} for s in ['train','validation','test']}
        self.assertFalse(groups['train']&groups['test'] or groups['train']&groups['validation'] or groups['test']&groups['validation'])
        self.assertFalse(set.union(*groups.values())&set(p['reserved_holdout_groups']))
        self.assertEqual(len(p['reserved_holdout_groups']),73)
        self.assertFalse(p['reserved_holdout_evaluated'])

    @unittest.skipUnless(Path('artifacts/dynamic_azure_adapted_20261020/model.joblib').exists(),'local model unavailable')
    def test_experimental_artifact_is_train_only_and_cannot_silently_load_as_v5(self):
        import joblib
        from autoscheduler.dynamic import DYNAMIC_FEATURE_NAMES
        from autoscheduler.model import load_model
        path=Path('artifacts/dynamic_azure_adapted_20261020/model.joblib')
        bundle=joblib.load(path)
        self.assertEqual(bundle['model'].policies,('No Switch','MLFQ','Round Robin','Priority RR'))
        self.assertEqual(bundle['model'].regressor.tree_.n_node_samples[0],216)
        self.assertEqual(tuple(bundle['metadata']['feature_names']),DYNAMIC_FEATURE_NAMES)
        with self.assertRaises(ValueError):load_model(path,DYNAMIC_FEATURE_NAMES)


if __name__=='__main__':unittest.main()
