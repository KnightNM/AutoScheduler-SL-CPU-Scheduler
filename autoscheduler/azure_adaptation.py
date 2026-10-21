"""One grouped Azure-proxy cost-tree experiment; no final-holdout consumption."""
import argparse
from collections import Counter,defaultdict
from contextlib import contextmanager
from dataclasses import asdict
import json
from pathlib import Path
import random
import signal
from statistics import mean
import time

import joblib
import numpy as np
from sklearn.dummy import DummyRegressor
from sklearn.metrics import mean_absolute_error,mean_squared_error,r2_score
from sklearn.tree import DecisionTreeRegressor

from autoscheduler.azure_generalization import DATA,MODEL,characteristics,load,sha,write
from autoscheduler.dynamic import (DYNAMIC_FEATURE_NAMES,_counterfactual_label,_policy_config,
    _training_states,extract_dynamic_features,run_dynamic,_percentile)
from autoscheduler.evaluation import DEPLOYABLE_ALGORITHMS,SCORE_WEIGHTS,score_result_against_reference
from autoscheduler.experiments import paired_bootstrap_ci
from autoscheduler.fairness import aggregate_fairness
from autoscheduler.model import PolicyCostModel
from scheduler.mlfq import mlfq
from simulator.process import Process
from simulator.simulator import run_simulation

OUTPUT=Path('results/azure_adapted_20261020')
ARTIFACTS=Path('artifacts/dynamic_azure_adapted_20261020')
ACTIONS=('No Switch','MLFQ','Round Robin','Priority RR')
SEED=20261022


@contextmanager
def budget(seconds):
    def expired(*_):raise TimeoutError(f'Fixed {seconds}s budget exceeded; retained, no replacement')
    previous=signal.signal(signal.SIGALRM,expired);signal.alarm(seconds)
    try:yield
    finally:signal.alarm(0);signal.signal(signal.SIGALRM,previous)


class PreemptiveProbe:
    def __init__(self):self.calls=0
    def predict(self,rows):
        self.calls+=1
        return [('Round Robin' if self.calls%2 else 'Priority RR') for _ in rows]


def references(jobs):
    return {name:run_simulation(name,fn,jobs,**kwargs) for name,(fn,kwargs) in DEPLOYABLE_ALGORITHMS.items()}


def protect():
    paths=[p for p in Path('results').rglob('*') if p.is_file() and OUTPUT not in p.parents]
    paths+=list(Path('artifacts').rglob('model.joblib'))
    paths += [DATA,Path('configs/research_status.json'),Path('configs/real_desktop_ml.json')]
    write(OUTPUT/'preserved_sha256.json',{str(p):sha(p) for p in paths})


def prepare(workloads,config):
    if (OUTPUT/'protocol.json').exists():return json.loads((OUTPUT/'protocol.json').read_text())
    group_map=json.loads(Path('results/dynamic_azure_generalization/selection_manifest.json').read_text())['all_source_groups']
    holdout=set(json.loads(Path('results/dynamic_azure_generalization/untouched_holdout_manifest.json').read_text())['genuinely_untouched_groups'])
    seen=set()
    for path,key in [('results/azure_external_pilot/selection.json',None),
                     ('results/dynamic_azure_generalization/selection_manifest.json','selected'),
                     ('results/real_source_dynamic_review_20261020/protocol.json','selected')]:
        obj=json.loads(Path(path).read_text());seen.update(w['workload_id'] for w in (obj[key] if key else obj))
    seen_groups={group_map[wid] for wid in seen}
    rng=random.Random(SEED);used=set();selected=[];pools={}
    specifications=[('medium',4,100000,lambda w,c:.05<=c['arrival_work_pending_fraction']<.5),
                    ('mixed_low',2,20000,lambda w,c:len(w['sources'])>1 and c['arrival_work_pending_fraction']<.05),
                    ('low',24,20000,lambda w,c:c['arrival_work_pending_fraction']<.05),
                    ('high',2,200000,lambda w,c:c['arrival_work_pending_fraction']>=.5)]
    for name,count,cap,predicate in specifications:
        pool=[]
        for w in workloads:
            g=group_map[w['workload_id']]
            if g in holdout or not 5<=len(w['processes'])<=100:continue
            c=characteristics(w)
            if c['total_cpu_proxy_ms']<=cap and predicate(w,c):pool.append((w,c,g))
        pool.sort(key=lambda x:x[0]['workload_id']);rng.shuffle(pool);taken=[]
        for w,c,g in pool:
            if g in used:continue
            used.add(g);taken.append({'workload_id':w['workload_id'],'source_group':g,'stratum':name,
                'cohort':w['cohort'],'sources':[{'function':s['HashFunction'],'day':s['day'],'source_row':s['source_row']} for s in w['sources']],
                'previous_workload_seen':w['workload_id'] in seen,'previous_source_group_seen':g in seen_groups,**c})
            if len(taken)==count:break
        # Assign complete provenance groups, before labels or scheduler outcomes.
        if name=='medium':splits=['train','train','validation','test']
        elif name=='mixed_low':splits=['train','test']
        elif name=='low':splits=['train']*15+['validation']*5+['test']*4
        else:splits=['train']*len(taken)
        for item,split in zip(taken,splits):item['split']=split;selected.append(item)
        pools[name]={'requested':count,'selected':len(taken),'eligible_workloads':len(pool),'max_cpu_proxy_ms':cap}
    assert len({w['source_group'] for w in selected})==len(selected)
    assert not ({w['source_group'] for w in selected}&holdout)
    protocol={'scope':'AZURE_PROXY_GROUPED_DEVELOPMENT_EXPERIMENT_ONLY','seed':SEED,'selected':selected,'pools':pools,
        'dataset_sha256':sha(DATA),'v5_model_sha256':sha(MODEL),'reserved_holdout_groups':sorted(holdout),
        'reserved_holdout_evaluated':False,'eligibility':list(ACTIONS),'feature_names':list(DYNAMIC_FEATURE_NAMES),
        'config':asdict(config),'weights':SCORE_WEIGHTS,'score_reference':list(DEPLOYABLE_ALGORITHMS),
        'split_rule':'One whole workload per connected function/owner/app provenance component; fixed stratum quotas, approximately 60/20/20. Prior-inspected groups are flagged; no untouched independent-test claim.',
        'sampling':'Six uniformly reservoir-sampled legal review states per trajectory, MLFQ and preemptive exploration; twelve maximum per workload. All whole input jobs retained.',
        'label_rule':'Feasible 20ms action until first safe review, then tuned MLFQ continuation to completion; relative to immediate MLFQ continuation; fixed five-static normalization. Future outcomes only in targets.',
        'settings':[{'max_depth':3,'min_samples_leaf':5},{'max_depth':5,'min_samples_leaf':5}],
        'selection':'Safety-gate eligibility first, then realized validation score; save diagnostic candidate if none eligible; no refit after validation.',
        'budgets':{'label_workload_seconds':60,'evaluation_policy_seconds':20,'feasibility_seconds':10},
        'runtime_failure_rule':'Retain every timeout, no replacements, no reduced normalization. Stop before fitting unless train/validation have nonconstant pooled action costs; test target diagnostics only after freezing.',
        'final_holdout_rule':'Preserve 73 groups; not executed because heavy-queue coverage and repeated uncensored runtime are not established.'}
    write(OUTPUT/'protocol.json',protocol);return protocol


def regression(estimator,rows):
    x=[[r['features'][f] for f in DYNAMIC_FEATURE_NAMES] for r in rows];y=np.array([r['costs'] for r in rows])
    pred=np.asarray(estimator.predict(x));actual=y.ravel();predicted=pred.ravel()
    r2=float(r2_score(actual,predicted)) if np.var(actual)>0 else None
    selected=np.argmin(pred,axis=1);best=np.argmin(y,axis=1)
    # Reference labels explicitly prefer No Switch on exact ties.
    return {'decision_rows':len(rows),'decision_action_pairs':int(y.size),'groups':len({r['source_group'] for r in rows}),
        'mae':float(mean_absolute_error(actual,predicted)),'rmse':float(np.sqrt(mean_squared_error(actual,predicted))),
        'r_squared':r2,'r_squared_scope':'Pooled decision–action cost pairs; undefined when all targets constant',
        'strict_action_agreement':float(np.mean(selected==best)),
        'tie_aware_action_agreement':float(np.mean([y[i,j]<=np.min(y[i])+1e-12 for i,j in enumerate(selected)]))}


def evaluate(workloads,models,config,items):
    by_id={w['workload_id']:w for w in workloads};rows=[]
    for item in items:
        jobs=[Process(**p) for p in by_id[item['workload_id']]['processes']];results={};batch=[]
        registry={**DEPLOYABLE_ALGORITHMS,'Tuned MLFQ':(mlfq,{'quanta':(1,2,4),'aging_threshold':40})}
        for name in [*registry,*models]:
            row={'workload_id':item['workload_id'],'source_group':item['source_group'],'split':item['split'],'stratum':item['stratum'],'policy':name}
            started=time.monotonic();router=None
            try:
                with budget(20):
                    if name in models:router=run_dynamic(jobs,models[name],config);result=router.simulation
                    else:
                        fn,kwargs=registry[name];result=run_simulation(name,fn,jobs,**kwargs)
                results[name]=result;ds=router.decisions if router else []
                row.update(status='COMPLETE',avg_waiting_ms=result.avg_waiting_time,avg_response_ms=result.avg_response_time,
                    p95_response_ms=_percentile([p.response_time for p in result.process_metrics],.95),
                    avg_turnaround_ms=result.avg_turnaround_time,utilization_fraction=result.cpu_utilization,throughput_jobs_per_ms=result.throughput,
                    starvation=aggregate_fairness(result.process_metrics)['starvation_count'],context_switches=result.context_switches,
                    accepted_switches=sum(d.accepted for d in ds),nonaccepted_reviews=sum(not d.accepted for d in ds),
                    reasons=dict(Counter(d.reason for d in ds)),decision_examples=len(ds),
                    decision_p99_ms=router.transition_p99_ms if router else None)
                if name.startswith('Azure tree'):
                    assert not any(d.accepted and d.active in {'FCFS','Priority'} for d in ds)
            except TimeoutError as error:row.update(status='TIMEOUT',reason=str(error))
            row['wall_seconds']=time.monotonic()-started;batch.append(row)
        refs={p:results[p] for p in DEPLOYABLE_ALGORITHMS if p in results}
        for r in batch:r['weighted_score']=score_result_against_reference(results[r['policy']],refs) if r['policy'] in results and len(refs)==5 else None
        rows.extend(batch)
        print('evaluation',item['workload_id'],[(r['policy'],r['status']) for r in batch if r['status']!='COMPLETE'],flush=True)
    return rows


def gates_for(rows,policy,comparator):
    grouped=defaultdict(dict)
    for r in rows:grouped[r['workload_id']][r['policy']]=r
    pairs=[v for v in grouped.values() if v[policy]['status']==v[comparator]['status']=='COMPLETE' and v[policy]['weighted_score'] is not None and v[comparator]['weighted_score'] is not None]
    if not pairs:return {'eligible':False,'reason':'No completed pairs'}
    diffs={key:paired_bootstrap_ci([v[policy][key]-v[comparator][key] for v in pairs]) for key in ['weighted_score','p95_response_ms','starvation']}
    lat=max(v[policy]['decision_p99_ms'] for v in pairs)
    gates={'score':diffs['weighted_score']['ci_high']<0,'p95':diffs['p95_response_ms']['ci_high']<=0,
        'starvation':diffs['starvation']['mean']<=0,'latency':lat<10,'coverage':len(pairs)==len(grouped)}
    rr_pairs=[v for v in pairs if v['Round Robin']['status']=='COMPLETE' and v['Round Robin']['weighted_score'] is not None]
    gates['original_rr_score']=bool(rr_pairs) and paired_bootstrap_ci([v[policy]['weighted_score']-v['Round Robin']['weighted_score'] for v in rr_pairs])['ci_high']<=0
    gates['original_rr_p95']=bool(rr_pairs) and paired_bootstrap_ci([v[policy]['p95_response_ms']-v['Round Robin']['p95_response_ms'] for v in rr_pairs])['ci_high']<0
    return {'eligible':all(gates.values()),'gates':gates,'pairs':len(pairs),'differences':diffs,'max_workload_p99_ms':lat,
        'mean_score':mean(v[policy]['weighted_score'] for v in pairs),'comparator':comparator}


def run():
    if OUTPUT.exists():raise ValueError('Refuse to overwrite versioned experiment')
    protect();workloads,v5,config=load();protocol=prepare(workloads,config);by_id={w['workload_id']:w for w in workloads}
    rr=_policy_config(None);labels=[];outcomes=[];bench=[]
    # Benchmark metadata-selected largest CPU example from each feasible stratum.
    for stratum in ['low','mixed_low','medium']:
        item=max((w for w in protocol['selected'] if w['stratum']==stratum),key=lambda w:w['total_cpu_proxy_ms'])
        jobs=[Process(**p) for p in by_id[item['workload_id']]['processes']];start=time.monotonic()
        try:
            with budget(10):
                refs=references(jobs)
                states=_training_states(jobs,config,rr,'MLFQ',SEED,max_states=1)
                if states:
                    state,active,dwell=states[0]
                    _counterfactual_label(state,config.epoch_ticks,rr,ACTIONS,active,dwell,config=config,references=refs)
            bench.append({'workload_id':item['workload_id'],'stratum':stratum,'seconds':time.monotonic()-start,'status':'COMPLETE'})
        except TimeoutError as error:bench.append({'workload_id':item['workload_id'],'stratum':stratum,'seconds':time.monotonic()-start,'status':'TIMEOUT','reason':str(error)})
    write(OUTPUT/'feasibility.json',bench)
    if any(b['status']!='COMPLETE' for b in bench):
        write(OUTPUT/'BLOCKED.json',{'reason':'Representative finite-action labeling exceeded fixed feasibility budget; no model fitted','benchmarks':bench});return
    for index,item in enumerate(protocol['selected']):
        start=time.monotonic();local=[]
        try:
            with budget(60):
                jobs=[Process(**p) for p in by_id[item['workload_id']]['processes']];refs=references(jobs)
                for behavior in ['MLFQ','preemptive_probe']:
                    states=_training_states(jobs,config,rr,'MLFQ',SEED+index,
                        PreemptiveProbe() if behavior=='preemptive_probe' else None,max_states=6)
                    for state,active,dwell in states:
                        label,costs=_counterfactual_label(state,config.epoch_ticks,rr,ACTIONS,active,dwell,config=config,references=refs)
                        local.append({'workload_id':item['workload_id'],'source_group':item['source_group'],'split':item['split'],
                            'time':state.current_time,'active':active,'behavior':behavior,'label':label,
                            'features':extract_dynamic_features(state,active,dwell),'costs':[costs[a] for a in ACTIONS]})
            labels.extend(local);outcomes.append({'workload_id':item['workload_id'],'status':'COMPLETE','rows':len(local),'seconds':time.monotonic()-start})
        except TimeoutError as error:outcomes.append({'workload_id':item['workload_id'],'status':'TIMEOUT','reason':str(error),'seconds':time.monotonic()-start})
        print('label',item['workload_id'],outcomes[-1]['status'],len(local),flush=True)
        write(ARTIFACTS/'decision_costs.json',labels);write(OUTPUT/'label_outcomes.json',outcomes)
    splits={s:[r for r in labels if r['split']==s] for s in ['train','validation','test']}
    if any(not splits[s] or np.var([c for r in splits[s] for c in r['costs']])==0 for s in ['train','validation']):
        write(OUTPUT/'BLOCKED.json',{'reason':'Missing or constant pooled action-cost targets in a split; no informative regression experiment. No model fitted.','rows':{s:len(rs) for s,rs in splits.items()}});return
    x=[[r['features'][f] for f in DYNAMIC_FEATURE_NAMES] for r in splits['train']];y=[r['costs'] for r in splits['train']]
    candidates={};diagnostics={}
    dummy=DummyRegressor(strategy='mean').fit(x,y)
    for settings in protocol['settings']:
        name=f"Azure tree depth {settings['max_depth']}";tree=DecisionTreeRegressor(**settings,random_state=SEED).fit(x,y)
        candidates[name]=PolicyCostModel(tree,ACTIONS)
        diagnostics[name]={s:regression(tree,rs) for s,rs in splits.items() if s!='test'}
    dummy_metrics={s:regression(dummy,rs) for s,rs in splits.items() if s!='test'}
    validation=evaluate(workloads,candidates,config,[w for w in protocol['selected'] if w['split']=='validation'])
    valid_grouped=defaultdict(list)
    for r in validation:
        if r['status']=='COMPLETE' and r['weighted_score'] is not None:valid_grouped[r['policy']].append(r)
    common_ids={r['workload_id'] for r in validation}
    for p in [*DEPLOYABLE_ALGORITHMS,'Tuned MLFQ',*candidates]:common_ids&={r['workload_id'] for r in valid_grouped[p]}
    if not common_ids:write(OUTPUT/'BLOCKED.json',{'reason':'No common complete validation workloads; no candidate frozen'});return
    primary=min([*DEPLOYABLE_ALGORITHMS,'Tuned MLFQ'],key=lambda p:mean(r['weighted_score'] for r in valid_grouped[p] if r['workload_id'] in common_ids))
    eligibility={p:gates_for(validation,p,primary) for p in candidates}
    chosen=min(candidates,key=lambda p:(not eligibility[p]['eligible'],eligibility[p].get('mean_score',float('inf')),p))
    model=candidates[chosen]
    metadata={'schema':'azure_dynamic_cost_v1','feature_names':list(DYNAMIC_FEATURE_NAMES),'actions':list(ACTIONS),
        'dynamic_config':asdict(config),'selection':chosen,'primary_static':primary,'promoted':False,
        'source_protocol_sha256':sha(OUTPUT/'protocol.json'),'training_groups':sorted({r['source_group'] for r in splits['train']})}
    ARTIFACTS.mkdir(parents=True,exist_ok=True);joblib.dump({'model':model,'metadata':metadata},ARTIFACTS/'model.joblib')
    write(OUTPUT/'frozen_candidate.json',{'metadata':metadata,'validation_eligibility':eligibility,
        'model_sha256':sha(ARTIFACTS/'model.joblib'),'validation_rows':validation,'test_accessed':False})
    # Test is accessed only after artifact/settings/comparator are frozen.
    loaded=joblib.load(ARTIFACTS/'model.joblib');assert loaded['metadata']==metadata
    assert tuple(loaded['model'].policies)==ACTIONS and loaded['model'].regressor.n_features_in_==len(DYNAMIC_FEATURE_NAMES)
    model=loaded['model'];diagnostics[chosen]['test']=regression(model.regressor,splits['test'])
    dummy_metrics['test']=regression(dummy,splits['test'])
    test=evaluate(workloads,{'Azure tree':model,'Dynamic v5':v5},config,[w for w in protocol['selected'] if w['split']=='test'])
    fixed_metrics={s:{'mean_reference_cost':mean(r['costs'][0] for r in rs),'strict_action_agreement':mean(r['label']=='No Switch' for r in rs)} for s,rs in splits.items()}
    write(OUTPUT/'results.json',{'chosen':chosen,'primary_static':primary,'prediction_metrics':diagnostics[chosen],
        'dummy_metrics':dummy_metrics,'fixed_no_switch':fixed_metrics,'candidate_validation':eligibility,
        'validation_rows':validation,'test_rows':test,'test_vs_primary':gates_for(test,'Azure tree',primary),
        'test_vs_tuned':gates_for(test,'Azure tree','Tuned MLFQ'),'scope':protocol['scope'],
        'holdout_evaluated':False,'promoted':False,'training_occurred':True,
        'counts':{s:{'decision_rows':len(rs),'groups':len({r['source_group'] for r in rs})} for s,rs in splits.items()},
        'model_path':str(ARTIFACTS/'model.joblib'),'model_sha256':sha(ARTIFACTS/'model.joblib')})
    write(ARTIFACTS/'test_predictions.json',{'rows':[{'workload_id':r['workload_id'],'actual':r['costs'],
        'predicted':model.regressor.predict([[r['features'][f] for f in DYNAMIC_FEATURE_NAMES]])[0].tolist()} for r in splits['test']]})


if __name__=='__main__':
    argparse.ArgumentParser(description=__doc__).parse_args();run()
