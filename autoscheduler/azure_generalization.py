"""Azure generalization diagnostics: observed proxy workloads, no model fitting."""
import argparse
from collections import Counter
import cProfile
from dataclasses import asdict
import csv
import hashlib
import json
from pathlib import Path
import pstats
import signal
from statistics import mean, pvariance
import time

from autoscheduler.dynamic import DYNAMIC_FEATURE_NAMES, DYNAMIC_POLICY_NAMES, DynamicRouterConfig, run_dynamic, _percentile
from autoscheduler.evaluation import DEPLOYABLE_ALGORITHMS
from autoscheduler.model import load_model, load_model_metadata
from simulator.process import Process
from simulator.simulator import run_simulation

OUTPUT=Path('results/dynamic_azure_generalization')
DATA=Path('AzureWorkloads/cleaned/evaluation_workloads.json')
MODEL=Path('artifacts/dynamic_v5_20261019/policy_cost/model.joblib')


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2)+'\n')


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def characteristics(w):
    jobs=sorted(w['processes'],key=lambda p:(p['arrival_time'],p['pid']))
    arrivals=[p['arrival_time'] for p in jobs];bursts=[p['burst_time'] for p in jobs]
    gaps=[b-a for a,b in zip(arrivals,arrivals[1:])]
    pending=0;last=arrivals[0];overlap=0;max_pending=0
    for p in jobs:
        pending=max(0,pending-(p['arrival_time']-last));overlap+=pending>0
        pending+=p['burst_time'];max_pending=max(max_pending,pending);last=p['arrival_time']
    span=arrivals[-1]-arrivals[0]
    return {'processes':len(jobs),'arrival_first_ms':arrivals[0],'arrival_last_ms':arrivals[-1],
        'arrival_span_ms':span,'distinct_arrivals':len(set(arrivals)),
        'interarrival_mean_ms':mean(gaps) if gaps else None,'interarrival_p95_ms':_percentile(gaps,.95) if gaps else None,
        'interarrival_cv':pvariance(gaps)**.5/mean(gaps) if gaps and mean(gaps)>0 else None,
        'total_cpu_proxy_ms':sum(bursts),'burst_mean_ms':mean(bursts),'burst_cv':pvariance(bursts)**.5/mean(bursts),
        'burst_min_ms':min(bursts),'burst_max_ms':max(bursts),'arrival_work_pending_fraction':overlap/len(jobs),
        'max_aggregate_pending_work_ms':max_pending,'cpu_per_exposure':sum(bursts)/w['exposure_ms'],
        'neutral_priorities_only':all(p['priority']==0 for p in jobs),'io_observed':False}


def load():
    workloads=json.loads(DATA.read_text())['workloads']
    metadata=load_model_metadata(MODEL);config=DynamicRouterConfig(**metadata['dynamic_config'])
    model=load_model(MODEL,DYNAMIC_FEATURE_NAMES,expected_dynamic_config=config)
    return workloads,model,config


def diagnosis():
    target=OUTPUT/'original_pilot_diagnosis.json'
    if target.exists(): raise ValueError('Never overwrite completed diagnosis')
    workloads,model,config=load()
    selection=json.loads(Path('results/azure_external_pilot/selection.json').read_text())
    completed=set()
    with Path('results/azure_external_pilot/workloads.csv').open() as stream:
        old=list(csv.DictReader(stream));completed={r['workload_id'] for r in old}
    rows=[];examples=[];calls=[]
    original_predict=model.predict
    def recorded_predict(matrix):
        result=original_predict(matrix);calls.append(str(result[0]));return result
    model.predict=recorded_predict
    for item in selection:
        if item['workload_id'] not in completed:continue
        w=next(w for w in workloads if w['workload_id']==item['workload_id']);jobs=[Process(**p) for p in w['processes']]
        calls.clear();started=time.monotonic();router=run_dynamic(jobs,model,config)
        assert len(calls)==len(router.decisions),'Every review must invoke model exactly once'
        record={'workload_id':w['workload_id'],'stratum':item['stratum'],'cohort':w['cohort'],**characteristics(w),
            'makespan_ms':router.simulation.makespan,'idle_ms':router.simulation.idle_time,
            'wall_seconds_instrumented':time.monotonic()-started,'decision_opportunities':len(router.decisions),
            'model_invocations':len(calls),'raw_actions':dict(Counter(calls)),
            'accepted_switches':sum(d.accepted for d in router.decisions),
            'reasons':dict(Counter(d.reason for d in router.decisions)),
            'reviews_with_competing_ready_jobs':sum(d.features['ready_count']>=2 for d in router.decisions),
            'reviews_with_unserved_ready_jobs':sum(d.features['first_service_ready_count']>0 for d in router.decisions),
            'fallback_reviews':sum(d.confidence<config.confidence_threshold or d.reason.startswith('fallback') for d in router.decisions),
            'decision_p99_ms_instrumented':router.transition_p99_ms,
            'postguard_rejected_switches':sum(not d.accepted and d.selected!=DYNAMIC_POLICY_NAMES[int(d.features['active_policy_index'])] for d in router.decisions)}
        proposed=[(raw,d) for raw,d in zip(calls,router.decisions) if raw not in ('No Switch',DYNAMIC_POLICY_NAMES[int(d.features['active_policy_index'])])]
        record['raw_proposed_departures']=len(proposed)
        record['raw_departure_disposition']=dict(Counter(d.reason for _,d in proposed))
        record['raw_no_switch_decisions']=sum(raw=='No Switch' for raw in calls)
        record['jobs_finishing_before_first_review']=sum(m.completion_time<= (router.decisions[0].time if router.decisions else router.simulation.makespan) for m in router.simulation.process_metrics)
        active=config.initial_policy;begin=0;intervals=[]
        for d in router.decisions:
            if d.accepted:
                intervals.append({'start_ms':begin,'end_ms':d.time,'policy':active});begin=d.time;active=d.active
        intervals.append({'start_ms':begin,'end_ms':router.simulation.makespan,'policy':active})
        record['active_policy_timeline']=intervals
        previous=next(r for r in old if r['workload_id']==w['workload_id'] and r['policy']=='Dynamic v5')
        record['original_metrics_reproduced']=all(abs(getattr(router.simulation,k)-float(previous[v]))<1e-9 for k,v in
            [('avg_waiting_time','avg_waiting_ms'),('avg_response_time','avg_response_ms'),('avg_turnaround_time','avg_turnaround_ms')])
        assert record['original_metrics_reproduced']
        examples.extend({'workload_id':w['workload_id'],'raw_model_action':raw,**asdict(d)} for raw,d in list(zip(calls,router.decisions))[:3])
        rows.append(record);print(w['workload_id'],len(calls),record['raw_actions'],record['reasons'],flush=True)
    write(target,{'rows':rows,'examples':examples,'config':asdict(config),'model_sha256':sha(MODEL),
        'measurement_note':'Raw model.predict actions recorded before safety processing; actual algorithms and safeguards unchanged. Instrumented latency is diagnostic only.'})


def profile_peak(seconds=8, filename='peak_profile.json'):
    target=OUTPUT/filename
    if target.exists():raise ValueError('Never overwrite a profile')
    workloads,model,config=load()
    w=next(w for w in workloads if w['workload_id']=='azure-refined-d13-0207')
    rows=[]
    def expired(*_):raise TimeoutError('Bounded profiling interval expired')
    previous=signal.signal(signal.SIGALRM,expired)
    try:
        for policy in ('Priority RR','MLFQ','Dynamic v5'):
            profile=cProfile.Profile();start=time.monotonic();complete=True
            signal.alarm(seconds)
            try:
                profile.enable();jobs=[Process(**p) for p in w['processes']]
                if policy=='Dynamic v5':run_dynamic(jobs,model,config)
                else:
                    fn,kwargs=DEPLOYABLE_ALGORITHMS[policy];run_simulation(policy,fn,jobs,**kwargs)
            except TimeoutError:complete=False
            finally:profile.disable();signal.alarm(0)
            stats=pstats.Stats(profile)
            rows.append({'policy':policy,'completed_with_profiler':complete,'seconds':time.monotonic()-start,
                'top_cumulative':[{'file':Path(key[0]).name,'line':key[1],'function':key[2],'calls':value[1],
                    'self_seconds':value[2],'cumulative_seconds':value[3]} for key,value in
                    sorted(stats.stats.items(),key=lambda kv:kv[1][3],reverse=True)[:18]]})
            print(policy,complete,flush=True)
    finally:signal.signal(signal.SIGALRM,previous)
    write(target,{'workload_id':w['workload_id'],'profiling_seconds_per_policy':seconds,'characteristics':characteristics(w),
        'source_sha256':{p:sha(p) for p in ('simulator/engine.py','autoscheduler/dynamic.py')},
        'rows':rows,'note':'Bounded partial profiles, not scheduling results. No CPU-time rescaling or process subsampling.'})


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('mode',choices=('diagnose','profile','profile-after'))
    parser.add_argument('--output',type=Path,default=OUTPUT)
    args=parser.parse_args()
    OUTPUT=args.output
    if args.mode=='diagnose':diagnosis()
    elif args.mode=='profile-after':profile_peak(filename='peak_profile_after.json')
    else:profile_peak()
