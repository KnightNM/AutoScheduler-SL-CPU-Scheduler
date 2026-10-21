"""One bounded external Azure-derived robustness pilot; no fitting or tuning."""
import argparse
from collections import Counter
import csv
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import random
import signal
from statistics import mean
import time

from autoscheduler.dynamic import DYNAMIC_FEATURE_NAMES, DynamicRouterConfig, _percentile, run_dynamic
from autoscheduler.evaluation import DEPLOYABLE_ALGORITHMS, SCORE_WEIGHTS, score_result_against_reference
from autoscheduler.model import load_model, load_model_metadata
from scheduler.mlfq import mlfq
from simulator.process import Process
from simulator.simulator import run_simulation

DATA = Path('AzureWorkloads/cleaned/evaluation_workloads.json')
MODEL = Path('artifacts/dynamic_v5_20261019/policy_cost/model.joblib')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_payload(payload):
    if payload.get('schema_version') != 2 or payload.get('time_unit') != 'ms' or payload.get('duration_method') != 'ceil_daily_wall_clock_mean_ms':
        raise ValueError('Expected Azure schema 2, ms ticks and the documented wall-clock mean proxy; no rescaling allowed')


def select_workloads(payload, seed):
    rng=random.Random(seed)
    selected, pools = [], {}
    definitions=[('low_load',3,'retained_control','low_rate',100,20000),
        ('medium_load',3,'retained_control','medium_rate',100,20000),
        ('high_rate_control',3,'retained_control','high_rate',100,20000),
        ('mixed_functions',3,'retained_control','mixed_observed_durations',100,20000),
        ('high_load_hour_sample',2,'high_load_hour_sample',None,2000,10000),
        ('peak_rate_snapshot',1,'local_rate_snapshot',None,2000,130000)]
    for stratum,count,cohort,reason,max_jobs,max_cpu in definitions:
        relevant=[w for w in payload['workloads'] if w['cohort']==cohort and
                  (reason is None or any(r.startswith(reason) for r in w['reasons']))]
        pool=sorted([w for w in relevant if w['job_count']<=max_jobs and
                     sum(p['burst_time'] for p in w['processes'])<=max_cpu],key=lambda w:w['workload_id'])
        if len(pool)<count: raise ValueError(f'Insufficient bounded existing workloads for {stratum}')
        chosen=rng.sample(pool,count)
        selected.extend((stratum,w) for w in chosen)
        pools[stratum]={'requested':count,'azure_cohort':cohort,'reason_prefix':reason,
            'max_processes':max_jobs,'max_total_proxy_cpu_ms':max_cpu,'matching_before_caps':len(relevant),
            'eligible_after_caps':len(pool),'excluded_by_caps':len(relevant)-len(pool),
            'not_selected_eligible':len(pool)-count,'eligible_ids':[w['workload_id'] for w in pool]}
    assert len({w['workload_id'] for _,w in selected})==len(selected)
    return selected,pools


def metrics(result, references):
    return {'avg_waiting_ms':result.avg_waiting_time,'avg_response_ms':result.avg_response_time,
        'avg_turnaround_ms':result.avg_turnaround_time,
        'p95_response_ms':_percentile([m.response_time for m in result.process_metrics],.95),
        'throughput_jobs_per_ms':result.throughput,'utilization_fraction':result.cpu_utilization,
        'weighted_score':score_result_against_reference(result,references)}


def run(output,seed=20261019):
    if output.exists(): raise ValueError('Use a new output directory; never overwrite an evaluation')
    payload=json.loads(DATA.read_text());validate_payload(payload)
    selected,pools=select_workloads(payload,seed)
    status=json.loads(Path('configs/research_status.json').read_text())
    tuned=status['recommended_static']['parameters']
    protected=[DATA,MODEL,Path('configs/research_status.json'),Path('configs/real_desktop_ml.json'),
               Path('artifacts/demo_tree.json'),Path('results/dynamic_v5_20261019/research_summary.json'),
               Path('results/dynamic_v6_20261019/research_summary.json')]
    hashes={str(p):digest(p) for p in protected if p.exists()}
    model,config,model_error=None,None,None
    try:
        config=DynamicRouterConfig(**load_model_metadata(MODEL)['dynamic_config'])
        model=load_model(MODEL,DYNAMIC_FEATURE_NAMES,expected_dynamic_config=config)
    except (FileNotFoundError,ValueError) as error:
        model_error=str(error)
    protocol={'status':'SMALL_EXTERNAL_AZURE_DERIVED_PILOT','seed':seed,'data':str(DATA),'dataset_sha256':hashes[str(DATA)],
        'source':'Microsoft Azure Functions 2019 revision 2; Shahrad et al., Serverless in the Wild, USENIX ATC 2020; CC-BY',
        'time_interpretation':'1 tick = 1 ms; no rescaling or calibration',
        'algorithms':list(DEPLOYABLE_ALGORITHMS)+['Tuned MLFQ']+(['Dynamic v5'] if model is not None else []),
        'static_parameters':{name:kwargs for name,(_,kwargs) in DEPLOYABLE_ALGORITHMS.items()},'tuned_parameters':tuned,
        'dynamic_model':str(MODEL),'dynamic_config':asdict(config) if config else None,'dynamic_feature_contract':list(DYNAMIC_FEATURE_NAMES),
        'score_weights':SCORE_WEIGHTS,'score_reference':list(DEPLOYABLE_ALGORITHMS),
        'score_scope':'Fixed five eligible static-policy bounds within each workload; same weights; NOT comparable to historical six-reference scores.',
        'selection_pools':pools,'selection':'Seeded sample of ID-sorted pools, CPU/process caps before any scheduling outcomes; whole existing workloads only.',
        'runtime_budget_seconds_per_workload':90,'on_timeout':'Exclude whole workload from every policy; retain reason; never replace it.',
        'no_fitting_or_tuning':True,'protected_sha256':hashes,
        'source_sha256':{p:digest(p) for p in ('autoscheduler/azure_external_pilot.py','autoscheduler/evaluation.py','simulator/engine.py','autoscheduler/dynamic.py')}}
    selection=[]
    for group,w in selected:
        selection.append({'stratum':group,**{key:w.get(key) for key in ('workload_id','cohort','day','start_minute','job_count','reasons','observed_count','exposure_ms','sampling_fraction','reference_arrival_rate_per_second','realized_arrival_rate_per_second','source_rows')},
            'total_proxy_cpu_ms':sum(p['burst_time'] for p in w['processes']),'function_count':len(w.get('sources',[]))})
    output.mkdir(parents=True)
    def write(name,value): (output/name).write_text(json.dumps(value,indent=2)+'\n')
    write('protocol.json',protocol);write('selection.json',selection)
    rows,excluded=[],[]
    def expired(*_): raise TimeoutError('Prespecified 90-second whole-workload runtime budget exceeded')
    previous=signal.signal(signal.SIGALRM,expired)
    try:
        for group,w in selected:
            print(w['workload_id'],group,w['job_count'],flush=True)
            signal.alarm(90)
            start=time.monotonic()
            try:
                jobs=[Process(**p) for p in w['processes']]
                refs={name:run_simulation(name,fn,jobs,**kwargs) for name,(fn,kwargs) in DEPLOYABLE_ALGORITHMS.items()}
                results={**refs,'Tuned MLFQ':run_simulation('Tuned MLFQ',mlfq,jobs,**tuned)}
                if model is not None: results['Dynamic v5']=run_dynamic(jobs,model,config).simulation
                for name,result in results.items():
                    rows.append({'workload_id':w['workload_id'],'stratum':group,'azure_cohort':w['cohort'],'job_count':w['job_count'],
                                 'policy':name,**metrics(result,refs)})
            except TimeoutError as error:
                excluded.append({'workload_id':w['workload_id'],'stratum':group,'reason':str(error)})
            finally: signal.alarm(0)
            print('elapsed_seconds',round(time.monotonic()-start,2),flush=True)
    finally: signal.signal(signal.SIGALRM,previous)
    fields=list(rows[0]) if rows else []
    if rows:
        with (output/'workloads.csv').open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(rows)
    numeric=list(metrics.__annotations__) # Metric keys are taken from actual rows below.
    numeric=['avg_waiting_ms','avg_response_ms','avg_turnaround_ms','p95_response_ms','throughput_jobs_per_ms','utilization_fraction','weighted_score']
    def aggregate(items):
        return {name:{key:mean(r[key] for r in items if r['policy']==name) for key in numeric} for name in dict.fromkeys(r['policy'] for r in items)}
    complete={r['workload_id'] for r in rows}
    summary={'status':protocol['status'],'attempted_workloads':len(selected),'completed_workloads':len(complete),
        'selected_strata_counts':dict(Counter(g for g,_ in selected)),
        'completed_strata_counts':dict(Counter(g for g,w in selected if w['workload_id'] in complete)),
        'completed_azure_cohort_counts':dict(Counter(w['cohort'] for _,w in selected if w['workload_id'] in complete)),
        'processes_over_100':sum(w['job_count']>100 for _,w in selected if w['workload_id'] in complete),
        'policy_means':aggregate(rows),'by_stratum':{g:aggregate([r for r in rows if r['stratum']==g]) for g in dict.fromkeys(r['stratum'] for r in rows)},
        'aggregation':'Unweighted mean over complete workloads; not invocation-weighted or representative Azure performance. Throughput/utilization use simulator start-to-completion, not full source exposure.',
        'ml_inference_evaluated':model is not None and bool(rows),'ml_model':str(MODEL) if model is not None else None,'ml_unavailable_reason':model_error,
        'external_selection_accuracy':None,'selection_accuracy_reason':'No matching fitted six-policy classifier binary; dynamic excursion actions are not comparable to whole-workload static reference labels.',
        'excluded_workloads':excluded,'score_scope':protocol['score_scope'],'time_interpretation':protocol['time_interpretation'],
        'limitations':['Daily wall-clock means proxy CPU demand; individual CPU/I/O demand is unavailable.',
            'Arrivals are reconstructed from minute bins; snapshots assume conditional uniform order statistics, not observed microbursts.',
            'All priorities are neutral zero and no I/O bursts are supplied by Azure.',
            'Frozen 2-ms RR quanta, 8/20/40-ms aging and 10-ms dynamic epochs were not calibrated for Azure; synthetic-to-ms feature/domain shift remains.',
            'Small, CPU-budget-biased purposeful strata; possible source-hour overlap; no significance, population ranking or kernel-validation claims.']}
    assert all(digest(p)==h for p,h in hashes.items()),'Protected input/artifact changed'
    summary['protected_hashes_unchanged']=True
    write('summary.json',summary)
    report=['# Small external Azure-derived pilot','',protocol['source'],'',
        f"Fixed selection seed {seed}; {len(selected)} attempted, {len(complete)} completed workloads. No fitting, tuning, regeneration or rescaling.",'',
        'Whole-workload selections and pool exclusions: `selection.json` and `protocol.json`; outcomes: `workloads.csv`.','',
        f"Completed strata: {summary['completed_strata_counts']}. Azure cohorts: {summary['completed_azure_cohort_counts']}.",'',
        '| Policy | Avg wait ms | Avg response ms | Avg turnaround ms | Mean workload P95 ms | Jobs/ms | Utilization fraction | Weighted score |',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    for name,value in summary['policy_means'].items(): report.append('| '+name+' | '+' | '.join(f'{value[k]:.6f}' for k in numeric)+' |')
    report+=['',summary['aggregation'],'',protocol['score_scope'],'',
        'Eligible static policies only: SJF/SRTF are not part of the realistic reference set. No scheduler settings or score weights changed.',
        '',f"Dynamic v5 inference evaluated: {summary['ml_inference_evaluated']}. External algorithm-selection accuracy: unavailable. {summary['selection_accuracy_reason']}",
        '', 'Per-stratum metrics are in `summary.json`; pooled numbers are descriptive only. No policy/model is promoted.', '', '## Limitations','']
    report+=['- '+line for line in summary['limitations']]
    report+=['',f'Runtime exclusions (not replaced): {excluded}.', '', 'All protected dataset/model/report checksums match. This is not real CPU scheduler validation.']
    (output/'REPORT.md').write_text('\n'.join(report)+'\n')
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,default=Path('results/azure_external_pilot'))
    run(parser.parse_args().output)
