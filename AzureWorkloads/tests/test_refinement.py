"""Selection-only tests; never extract or clean the existing observations."""
from pathlib import Path
import sys
import unittest
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))


class SamplingTests(unittest.TestCase):
    def test_apportion_preserves_active_cells_and_exact_budget(self):
        from refine_workloads import apportion
        counts=np.array([[10**9,1,0,1],[2,40000,0,10]])
        result=apportion(counts,2000,42)
        self.assertEqual(result.sum(),2000)
        self.assertTrue((result[counts>0]>0).all())
        self.assertTrue((result[counts==0]==0).all())
        self.assertTrue((result<=counts).all())
        np.testing.assert_array_equal(result,apportion(counts,2000,42))

    def test_sampling_does_not_expand_the_population(self):
        from refine_workloads import sample_sources
        source=dict(day=1,source_row=2,duration_row=2,HashOwner='o',HashApp='a',HashFunction='f',
                    Trigger='http',Average=1,counts=[10**10]+[0]*59,start_minute=0)
        sources=sample_sources([source],2000,42)
        self.assertEqual(len(sources[0]['sampled_ordinals'][0]),2000)
        ordinals=sources[0]['sampled_ordinals'][0]
        self.assertEqual(len(set(ordinals)),2000)
        self.assertTrue(all(1<=i<=10**10 for i in ordinals))
        self.assertEqual(sources,sample_sources([source],2000,42))
        self.assertEqual(sources[0]['counts'][0],10**10)

    def test_contiguous_snapshot_is_bounded_and_approximately_rate_preserving(self):
        from refine_workloads import snapshot_source
        from convert_workloads import reconstruct
        source=dict(day=1,source_row=2,duration_row=2,HashOwner='o',HashApp='a',HashFunction='f',
                    Trigger='http',Average=1,counts=[60000]+[0]*59,start_minute=60)
        sampled,origin,exposure=snapshot_source(source,2000,42)
        jobs=reconstruct('w',[sampled],42,origin_ms=origin)
        self.assertEqual(len(jobs),2000)
        self.assertTrue(0<=jobs[0]['arrival_time']<=jobs[-1]['arrival_time']<exposure<=60000)
        self.assertLess(abs(2000/(exposure/1000)-1000)/1000,.1)
        self.assertEqual(jobs,reconstruct('w',[sampled],42,origin_ms=origin))
        self.assertEqual(len({j['invocation_ordinal'] for j in jobs}),2000)
        self.assertTrue(all(j['source_minute']==61 for j in jobs))

    def test_control_reconstruction_is_unchanged(self):
        from refine_workloads import sample_sources
        from convert_workloads import reconstruct
        source=dict(day=1,source_row=2,duration_row=2,HashOwner='o',HashApp='a',HashFunction='f',
                    Trigger='http',Average=1,counts=[2,0,3],start_minute=0)
        # Full controls retain the original reconstruction, including offsets and PIDs.
        self.assertEqual(reconstruct('w',[source],42),reconstruct('w',sample_sources([source],2000,42),42))

    def test_invalid_count_cannot_be_reconstructed(self):
        from refine_workloads import apportion
        for counts in [[-1,2],[float('nan'),1],[.5,1]]:
            with self.subTest(counts=counts),self.assertRaises(ValueError):
                apportion(np.array(counts),2,42)

class RoundingTests(unittest.TestCase):
    def test_published_integers_have_no_added_error_and_zeros_stay_excluded(self):
        from report_azure import rounding_statistics
        result=rounding_statistics([0,1,2,4,10,float('nan')])
        self.assertEqual(result['zero_published_means'],1)
        self.assertEqual(result['positive_published_means'],4)
        self.assertEqual(result['absolute_error_ms']['max'],0)
        self.assertEqual(result['short_duration_bins'][0]['rows'],1)

    def test_fractional_short_duration_error_is_quantified(self):
        from report_azure import rounding_statistics
        result=rounding_statistics([.1,.5,1.2,2.25])
        self.assertAlmostEqual(result['relative_error_percent']['max'],900)
        self.assertAlmostEqual(result['absolute_error_ms']['max'],.9)


class RefinedIntegrationTests(unittest.TestCase):
    def test_selection_only_pipeline_and_validation_reject_tampered_fractions(self):
        import copy,csv,json,subprocess,tempfile
        import pandas as pd
        from common import KEY,MINUTES,STATS,dump
        from convert_workloads import reconstruct,PROCESS_FIELDS
        from extract_azure import sha256
        from validate_azure import validate
        scripts=Path(__file__).resolve().parents[1]/'scripts'
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'cleaned').mkdir();(root/'reports/baseline').mkdir(parents=True)
            invs=[];durs=[]
            for i,(function,average) in enumerate([('low',1),('high',2)],2):
                counts=[3]+[0]*1439 if function=='low' else [1000000 if j%60==0 else 0 for j in range(1440)]
                ids=dict(zip(KEY,['o','a',function]));stats=dict.fromkeys(STATS,average);stats['Count']=sum(counts)
                invs.append(dict(day=1,source_file='invocations_per_function_md.anon.d01.csv',**ids,Trigger='http',source_row=i,
                    **dict(zip(MINUTES,counts)),invocation_status='usable',**stats,duration_row=i,match_status='usable'))
                durs.append(dict(day=1,source_file='function_durations_percentiles.anon.d01.csv',**ids,source_row=i,**stats,duration_status='usable'))
            pd.DataFrame(invs).to_csv(root/'cleaned/azure_cleaned.csv',index=False)
            pd.DataFrame(durs).to_csv(root/'cleaned/azure_durations_cleaned.csv',index=False)
            source=dict(day=1,source_row=2,duration_row=2,HashOwner='o',HashApp='a',HashFunction='low',Average=1.0,Trigger='http',start_minute=0,counts=[3]+[0]*59)
            jobs=reconstruct('old',[source],42)
            w=dict(workload_id='old',day=1,start_minute=0,source_rows=[2],window_minutes=60,sources=[source],
                observed_count=3,observed_minute_counts=source['counts'],absolute_start_ms=0,quiet_fraction=59/60,fano=0,reasons=['quiet'],
                processes=[{k:j[k] for k in PROCESS_FIELDS} for j in jobs])
            dump(root/'reports/baseline/evaluation_workloads.json',dict(seed=42,workloads=[w]))
            dump(root/'reports/baseline/selection_summary.json',dict(seed=42,max_jobs=2000,days=[]))
            dump(root/'reports/baseline/protected_inputs.json',{f'cleaned/{name}':sha256(root/'cleaned'/name) for name in ['azure_cleaned.csv','azure_durations_cleaned.csv']})
            totals={kind:dict(original_rows=2,retained_rows=2,duplicates_dropped=0,missing_key_rows_dropped=0,missing_cells=0,invalid_cells=0,
                zero_cells=sum(int(invs[i][m]==0) for i in range(2) for m in MINUTES) if kind=='invocation' else 0) for kind in ['invocation','duration']}
            dump(root/'reports/cleaning_summary.json',dict(totals=totals))
            run=subprocess.run([sys.executable,str(scripts/'refine_workloads.py'),'--root',str(root)],capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stderr)
            result=validate(root,scripts.parents[1]);self.assertTrue(result['passed'])
            path=root/'cleaned/evaluation_workloads.json';payload=json.loads(path.read_text())
            self.assertEqual(payload['workloads'][0]['processes'],w['processes'])
            payload['workloads'][1]['sampling_fraction']=1
            dump(path,payload)
            with self.assertRaisesRegex(ValueError,'sampling fraction'):
                validate(root,scripts.parents[1])
