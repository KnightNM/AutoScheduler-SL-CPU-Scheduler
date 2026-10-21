"""Provenance-grouped Azure development baseline; untouched holdout, no training."""
from collections import Counter,defaultdict
import argparse
from dataclasses import asdict
import csv
import inspect
import json
from pathlib import Path
import random
import signal
from statistics import mean
import time

from autoscheduler.azure_generalization import OUTPUT,DATA,MODEL,characteristics,load,write,sha
from autoscheduler.dynamic import DYNAMIC_FEATURE_NAMES,DYNAMIC_POLICY_NAMES,run_dynamic,_percentile
from autoscheduler.evaluation import DEPLOYABLE_ALGORITHMS,SCORE_WEIGHTS,score_result_against_reference
from autoscheduler.experiments import paired_bootstrap_ci
from autoscheduler.fairness import aggregate_fairness
from scheduler.mlfq import mlfq
from simulator.process import Process
from simulator.simulator import run_simulation


def provenance_groups(workloads):
    parent={w['workload_id']:w['workload_id'] for w in workloads};owner={}
    def root(x):
        while parent[x]!=x:parent[x]=parent[parent[x]];x=parent[x]
        return x
    for w in workloads:
        for source in w['sources']:
            token=tuple(source[k] for k in ('HashOwner','HashApp','HashFunction'))
            if token in owner:
                a,b=root(w['workload_id']),root(owner[token]);parent[max(a,b)]=min(a,b)
            else:owner[token]=w['workload_id']
    return {w['workload_id']:root(w['workload_id']) for w in workloads}


def prepare(workloads):
    target=OUTPUT/'selection_manifest.json'
    if target.exists():return json.loads(target.read_text())
    groups=provenance_groups(workloads);stats={w['workload_id']:characteristics(w) for w in workloads}
    members=defaultdict(list)
    for w in workloads:members[groups[w['workload_id']]].append(w)
    peak_groups=sorted({groups[w['workload_id']] for w in workloads if w['cohort']=='local_rate_snapshot'},
        key=lambda g:min(stats[w['workload_id']]['total_cpu_proxy_ms'] for w in members[g] if w['cohort']=='local_rate_snapshot'))
    # Reserve the second independent peak-function component before outcomes.
    holdout={peak_groups[-1]};protected_dev={peak_groups[0]}
    mixed_groups={groups[w['workload_id']] for w in workloads if w['cohort']=='high_load_mixed_hour_sample'}-holdout
    if mixed_groups:protected_dev.add(min(mixed_groups))
    rng=random.Random(20261020);candidates=sorted(set(members)-holdout-protected_dev);rng.shuffle(candidates)
    holdout.update(candidates[:len(members)//4])
    previous=json.loads(Path('results/azure_external_pilot/selection.json').read_text())
    old_ids={w['workload_id'] for w in previous};old_groups={groups[w] for w in old_ids}
    selected=[];used=set();pools={}
    def choose(name,count,predicate,max_cpu,force_new_group=True):
        pool=[w for w in workloads if groups[w['workload_id']] not in holdout and w['workload_id'] not in old_ids
              and stats[w['workload_id']]['total_cpu_proxy_ms']<=max_cpu and predicate(w,stats[w['workload_id']])]
        pool.sort(key=lambda w:w['workload_id']);rng.shuffle(pool);taken=[]
        for w in pool:
            g=groups[w['workload_id']]
            if g in used and force_new_group:continue
            taken.append(w);used.add(g)
            if len(taken)==count:break
        for w in taken:selected.append({'stratum':name,'workload_id':w['workload_id'],'cohort':w['cohort'],
            'source_group':groups[w['workload_id']],'source_group_seen_in_previous_pilot':groups[w['workload_id']] in old_groups,
            'day':w['day'],'start_minute':w['start_minute'],'source_rows':w['source_rows'],
            'function_ids':[s['HashFunction'] for s in w['sources']],**stats[w['workload_id']]})
        pools[name]={'requested':count,'selected':len(taken),'eligible_before_group_uniqueness':len(pool),'max_cpu_proxy_ms':max_cpu}
    choose('peak_rate_snapshot',1,lambda w,c:w['cohort']=='local_rate_snapshot',200000)
    choose('mixed_high_hour',1,lambda w,c:w['cohort']=='high_load_mixed_hour_sample',4000000)
    choose('mixed_function_control',1,lambda w,c:w['cohort']=='retained_control' and len(w['sources'])>1,500000)
    choose('sustained_arrivals',3,lambda w,c:w['cohort']!='local_rate_snapshot' and c['processes']>=50
           and c['arrival_span_ms']>=.7*w['exposure_ms'] and c['arrival_work_pending_fraction']>=.05,2000000)
    choose('high_contention',4,lambda w,c:w['cohort']!='local_rate_snapshot' and c['arrival_work_pending_fraction']>=.5,1000000)
    choose('medium_contention',4,lambda w,c:.05<=c['arrival_work_pending_fraction']<.5 and c['processes']<=200,500000)
    choose('low_contention',4,lambda w,c:c['arrival_work_pending_fraction']<.05 and 5<=c['processes']<=100,150000)
    manifest={'status':'DEVELOPMENT_BASELINE_ONLY_NOT_FINAL_HOLDOUT','seed':20261020,'dataset_sha256':sha(DATA),
        'rules':'Whole existing workloads; deterministic shuffled ID-sorted pools; CPU caps and aggregate-arrival backlog thresholds before outcomes; no input alteration.',
        'contention_definition':'Fraction of arrivals finding positive aggregate unfinished CPU proxy work; policy-independent workload descriptor, not observed OS ready queues.',
        'provenance_rule':'Connected components sharing any owner/app/function across all days and hours; one selected workload per component.',
        'source_group_count':len(members),'holdout_groups':sorted(holdout),'holdout_workload_ids':sorted(w['workload_id'] for w in workloads if groups[w['workload_id']] in holdout),
        'holdout_policy_results_accessed':False,'selected':selected,'pools':pools,
        'timeouts':'20 seconds per policy, retain every result/failure. Scores unavailable unless all five reference policies complete. No replacements.',
        'protected_artifact_manifest':'artifacts/dynamic_azure_generalization/preserved_sha256.json',
        'model_sha256':sha(MODEL),'score_weights':SCORE_WEIGHTS,'score_reference':list(DEPLOYABLE_ALGORITHMS),
        'parameters':{n:k for n,(_,k) in DEPLOYABLE_ALGORITHMS.items()},'tuned_mlfq':{'quanta':[1,2,4],'aging_threshold':40,'context_switch_cost':0},
        'all_source_groups':groups}
    assert all(w['source_group'] not in holdout for w in selected)
    assert len({w['source_group'] for w in selected})==len(selected)
    write(target,manifest)
    # Metadata only for all 510 workloads. No other workload is simulated.
    write(OUTPUT/'population_characteristics.json',{'workloads':[{ 'workload_id':w['workload_id'],'cohort':w['cohort'],'source_group':groups[w['workload_id']],**stats[w['workload_id']]} for w in workloads]})
    return manifest


def training_bounds():
    report=json.loads(Path('results/dynamic_v5_20261019/policy_cost_training.json').read_text())
    train=set(report['split_groups']['train']);values={name:[] for name in DYNAMIC_FEATURE_NAMES}
    with Path('artifacts/dynamic_v5_20261019/training.csv').open() as stream:
        for row in csv.DictReader(stream):
            if int(row['seed']) in train:
                for name in values:values[name].append(float(row[name]))
    return {name:{'min':min(xs),'p05':_percentile(xs,.05),'p95':_percentile(xs,.95),'max':max(xs)} for name,xs in values.items()}


def evaluate():
    if (OUTPUT/'baseline_rows.json').exists():raise ValueError('Never overwrite evaluation')
    workloads,model,config=load();manifest=prepare(workloads);bounds=training_bounds()
    write(OUTPUT/'training_feature_bounds.json',{'scope':'Training trace groups only; no validation or test rows','bounds':bounds})
    by_id={w['workload_id']:w for w in workloads};rows=[];diagnostics=[]
    def expired(*_):raise TimeoutError('20-second per-policy limit; result unavailable, workload retained')
    previous=signal.signal(signal.SIGALRM,expired)
    try:
        for item in manifest['selected']:
            w=by_id[item['workload_id']];jobs=[Process(**p) for p in w['processes']];results={};new_rows=[]
            for name in list(DEPLOYABLE_ALGORITHMS)+['Tuned MLFQ','Dynamic v5']:
                print(w['workload_id'],item['stratum'],name,flush=True)
                row={'workload_id':w['workload_id'],'source_group':item['source_group'],'stratum':item['stratum'],'policy':name}
                calls=[];ood=Counter();cost_examples=[];last_cost=None
                original_predict=model.predict;original_regressor=model.regressor.predict
                def cost_predict(matrix,*args,**kwargs):
                    nonlocal last_cost
                    result=original_regressor(matrix,*args,**kwargs);last_cost=list(map(float,result[0]));return result
                def action_predict(matrix):
                    result=original_predict(matrix);calls.append(str(result[0]))
                    for key,value in zip(DYNAMIC_FEATURE_NAMES,matrix[0]):
                        if value<bounds[key]['min'] or value>bounds[key]['max']:ood[key]+=1
                    if len(cost_examples)<3:cost_examples.append({'features':dict(zip(DYNAMIC_FEATURE_NAMES,matrix[0])),'raw_action':str(result[0]),'predicted_action_costs':dict(zip(model.policies,last_cost))})
                    return result
                dispatch=[];start=time.monotonic();router=None
                signal.alarm(20)
                try:
                    if name=='Dynamic v5':
                        model.predict=action_predict;model.regressor.predict=cost_predict
                        router=run_dynamic(jobs,model,config);result=router.simulation
                    else:
                        if name=='Tuned MLFQ':fn,kwargs=mlfq,manifest['tuned_mlfq']
                        else:fn,kwargs=DEPLOYABLE_ALGORITHMS[name]
                        timing={'decision_times_ns':dispatch} if 'decision_times_ns' in inspect.signature(fn).parameters else {}
                        result=run_simulation(name,fn,jobs,**kwargs,**timing)
                    signal.alarm(0)
                    results[name]=result;fair=aggregate_fairness(result.process_metrics)
                    row.update(status='COMPLETE',avg_waiting_ms=result.avg_waiting_time,avg_response_ms=result.avg_response_time,
                        p95_response_ms=_percentile([p.response_time for p in result.process_metrics],.95),avg_turnaround_ms=result.avg_turnaround_time,
                        throughput_jobs_per_ms=result.throughput,utilization_fraction=result.cpu_utilization,starvation=fair['starvation_count'],
                        context_switches=result.context_switches,context_switch_cost_ms=result.context_switch_time,makespan_ms=result.makespan,
                        accepted_switches=sum(d.accepted for d in router.decisions) if router else 0,
                        decision_p99_ms=router.transition_p99_ms if router else (_percentile(dispatch,.99)/1e6 if dispatch else None),
                        latency_scope='instrumented routing including features/model/guards' if router else ('static ready selection only' if dispatch else 'not instrumented'))
                    if router:
                        assert len(calls)==len(router.decisions)
                        diagnostics.append({'workload_id':w['workload_id'],'source_group':item['source_group'],'complete':True,
                            'decisions':len(calls),'raw_actions':dict(Counter(calls)), 'reasons':dict(Counter(d.reason for d in router.decisions)),
                            'accepted_switches':row['accepted_switches'],'accepted_with_competition':sum(d.accepted and d.features['ready_count']>=2 for d in router.decisions),
                            'reviews_with_competition':sum(d.features['ready_count']>=2 for d in router.decisions),
                            'feature_outside_training_range_counts':dict(ood),'predicted_cost_examples':cost_examples,
                            'accepted_events':[{'time':d.time,'active':d.active,'reason':d.reason,'ready_count':d.features['ready_count']} for d in router.decisions if d.accepted][:20]})
                except TimeoutError as error:
                    signal.alarm(0);row.update(status='TIMEOUT',reason=str(error))
                    if name=='Dynamic v5':diagnostics.append({'workload_id':w['workload_id'],'source_group':item['source_group'],'complete':False,
                        'partial_model_invocations':len(calls),'partial_raw_actions':dict(Counter(calls)),'feature_outside_training_range_counts':dict(ood),'predicted_cost_examples':cost_examples})
                finally:
                    signal.alarm(0);model.predict=original_predict;model.regressor.predict=original_regressor
                row['wall_seconds']=time.monotonic()-start;new_rows.append(row)
                write(OUTPUT/'baseline_progress.json',{'rows':rows+new_rows,'diagnostics':diagnostics})
            refs={name:results[name] for name in DEPLOYABLE_ALGORITHMS if name in results}
            for row in new_rows:
                row['weighted_score']=score_result_against_reference(results[row['policy']],refs) if row['policy'] in results and len(refs)==5 else None
                row['score_status']='fixed five-policy bounds available' if len(refs)==5 else 'unavailable: one or more fixed references timed out'
            rows.extend(new_rows)
    finally:signal.signal(signal.SIGALRM,previous)
    write(OUTPUT/'baseline_rows.json',{'rows':rows,'holdout_evaluated':False,'config':asdict(config)})
    write(OUTPUT/'baseline_decisions.json',{'rows':diagnostics})
    return rows


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=OUTPUT)
    OUTPUT=parser.parse_args().output
    evaluate()
