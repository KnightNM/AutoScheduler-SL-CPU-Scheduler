"""Focused fixture-only checks for the bounded external pilot adapter."""
import unittest
import json
import csv
from pathlib import Path


class AzureExternalPilotTests(unittest.TestCase):
    def test_selection_is_deterministic_and_never_truncates_jobs(self):
        from autoscheduler.azure_external_pilot import select_workloads
        rows=[]
        for reason in ('low_rate_block_0','medium_rate_block_0','high_rate_block_0','mixed_observed_durations'):
            for i in range(4):
                rows.append({'workload_id':reason+str(i),'cohort':'retained_control','job_count':2,
                    'reasons':[reason],'processes':[{'pid':str(j),'arrival_time':j,'burst_time':2,'priority':0} for j in range(2)]})
        for cohort in ('high_load_hour_sample','local_rate_snapshot'):
            for i in range(3):
                rows.append({'workload_id':cohort+str(i),'cohort':cohort,'job_count':2000,'reasons':[],
                    'processes':[{'pid':str(j),'arrival_time':j,'burst_time':1,'priority':0} for j in range(2000)]})
        first,info=select_workloads({'workloads':rows},20261019)
        second,_=select_workloads({'workloads':list(reversed(rows))},20261019)
        self.assertEqual([w['workload_id'] for _,w in first],[w['workload_id'] for _,w in second])
        self.assertEqual(len(first),15)
        self.assertEqual(sum(w['job_count']>100 for _,w in first),3)
        self.assertTrue(all(len(w['processes'])==w['job_count'] for _,w in first))

    def test_time_contract_rejects_unannounced_rescaling(self):
        from autoscheduler.azure_external_pilot import validate_payload
        with self.assertRaisesRegex(ValueError,'ms'):
            validate_payload({'schema_version':2,'time_unit':'s','duration_method':'ceil_daily_wall_clock_mean_ms'})

    def test_metric_units_preserve_simulator_values(self):
        from autoscheduler.azure_external_pilot import metrics
        from autoscheduler.evaluation import compare_algorithms
        from simulator.process import Process
        results=compare_algorithms([Process('a',0,2),Process('b',1,2)])
        row=metrics(results['FCFS'],results)
        self.assertEqual(row['avg_waiting_ms'],.5)
        self.assertEqual(row['avg_response_ms'],.5)
        self.assertEqual(row['avg_turnaround_ms'],2.5)
        self.assertEqual(row['utilization_fraction'],1)
        self.assertEqual(row['throughput_jobs_per_ms'],.5)

    @unittest.skipUnless(Path('results/azure_external_pilot/summary.json').exists(),'pilot result not present')
    def test_saved_results_have_identical_policy_coverage_and_dashboard_provenance(self):
        from dashboard.adapter import catalog
        summary=json.loads(Path('results/azure_external_pilot/summary.json').read_text())
        with Path('results/azure_external_pilot/workloads.csv').open() as stream: rows=list(csv.DictReader(stream))
        workloads={r['workload_id'] for r in rows}
        self.assertEqual(len(workloads),summary['completed_workloads'])
        self.assertTrue(12<=len(workloads)<=20)
        expected=set(summary['policy_means'])
        self.assertTrue(all({r['policy'] for r in rows if r['workload_id']==w}==expected for w in workloads))
        self.assertEqual(catalog()['azure_external']['summary'],summary)
        self.assertEqual(catalog()['offline']['metadata'],json.loads(Path('artifacts/demo_tree.json').read_text()))


if __name__=='__main__': unittest.main()
