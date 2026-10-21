"""Compare optimization against preserved runtime, including I/O and overhead."""
import importlib.util
from pathlib import Path
import random
import sys
import unittest

from simulator.engine import simulate
from simulator.process import Process
from autoscheduler.dynamic import DynamicRouterConfig,run_dynamic


def original(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
    return module


@unittest.skipUnless(Path('artifacts/dynamic_azure_generalization/before_source').exists(),'local preserved runtime not available')
class RuntimeEquivalenceTests(unittest.TestCase):
    def test_static_policies_match_original_with_io_aging_arrivals_and_switch_cost(self):
        old=original('azure_original_engine','artifacts/dynamic_azure_generalization/before_source/simulator/engine.py')
        for seed in range(8):
            rng=random.Random(seed)
            jobs=[Process(f'P{i}',rng.randrange(12),10+i,rng.randrange(5),cpu_bursts=(2,8+i),io_bursts=(2+i,)) for i in range(7)]
            for policy,kwargs in [('fcfs',{}),('rr',{'quantum':2}),('priority',{}),('priority_rr',{'quantum':2,'aging_interval':8,'context_switch_cost':1}),('mlfq',{'queue_quanta':(1,2,4),'aging_threshold':3,'context_switch_cost':1})]:
                with self.subTest(seed=seed,policy=policy):
                    expected=old.simulate(jobs,policy,**kwargs);actual=simulate(jobs,policy,**kwargs)
                    self.assertEqual(actual,expected)

    def test_dynamic_policy_traces_and_safety_decisions_match_original(self):
        old=original('azure_original_dynamic','artifacts/dynamic_azure_generalization/before_source/autoscheduler/dynamic.py')
        class Proposal:
            def predict(self,rows):return ['Priority RR']*len(rows)
        config=DynamicRouterConfig(epoch_ticks=3,dwell_epochs=2,initial_policy='MLFQ',fallback_policy='MLFQ',mlfq_quanta=(1,2,4),mlfq_aging_threshold=3)
        jobs=[Process(f'P{i}',i,20+i,i%3,cpu_bursts=(3,17+i),io_bursts=(7,)) for i in range(8)]
        expected=old.run_dynamic(jobs,Proposal(),config);actual=run_dynamic(jobs,Proposal(),config)
        self.assertEqual(actual.simulation,expected.simulation)
        fields=lambda result:[(d.time,d.selected,d.active,d.accepted,d.reason,d.features) for d in result.decisions]
        self.assertEqual(fields(actual),fields(expected))
