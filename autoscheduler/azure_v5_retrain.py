"""One exact-v5 Azure refit; fixed saved groups, one fit, one test comparison."""
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path
from statistics import mean
import time
from types import SimpleNamespace

import joblib
import numpy as np
from sklearn.tree import DecisionTreeRegressor

from autoscheduler.azure_adaptation import (ACTIONS, SEED, PreemptiveProbe, budget,
    references, regression)
from autoscheduler.azure_generalization import DATA, MODEL, load, sha, write
from autoscheduler.dynamic import (DYNAMIC_FEATURE_NAMES, _counterfactual_label,
    _policy_config, _training_states, dynamic_action_names, extract_dynamic_features,
    run_dynamic, _percentile)
from autoscheduler.evaluation import DEPLOYABLE_ALGORITHMS, score_result_against_reference
from autoscheduler.experiments import paired_bootstrap_ci
from autoscheduler.fairness import aggregate_fairness
from autoscheduler.model import PolicyCostModel, load_model
from scheduler.mlfq import mlfq
from simulator.process import Process
from simulator.simulator import run_simulation

SOURCE=Path('results/azure_adapted_20261020')
OUT=Path('results/dynamic_v5_azure_retrained_20261020')
ART=Path('artifacts/dynamic_v5_azure_retrained')
NAME='Azure-retrained v5'


def validate_splits(rows,holdout):
    assigned={}
    for row in rows:
        group,split=row['source_group'],row['split']
        if group in holdout or assigned.get(group,split)!=split:
            raise ValueError('Source group overlaps splits or reserved final holdout')
        assigned[group]=split


def cached_references(rows,workload_id):
    fields={'avg_waiting_time':'avg_waiting_ms','avg_response_time':'avg_response_ms',
        'avg_turnaround_time':'avg_turnaround_ms','cpu_utilization':'utilization_fraction',
        'throughput':'throughput_jobs_per_ms'}
    found={r['policy']:SimpleNamespace(**{a:r[b] for a,b in fields.items()})
        for r in rows if r['workload_id']==workload_id and r['policy'] in DEPLOYABLE_ALGORITHMS
        and r['status']=='COMPLETE'}
    if set(found)!=set(DEPLOYABLE_ALGORITHMS):raise ValueError('Incomplete frozen static score bounds')
    return found


class MeanCosts:
    def __init__(self,targets):self.costs=np.mean(targets,axis=0)
    def predict(self,x):return np.tile(self.costs,(len(x),1))


def run():
    if OUT.exists() or ART.exists():raise ValueError('Refuse overwrite or repeat experiment')
    workloads,original,config=load()
    protocol=json.loads((SOURCE/'protocol.json').read_text())
    old_results=json.loads((SOURCE/'results.json').read_text())
    old_labels=json.loads(Path('artifacts/dynamic_azure_adapted_20261020/decision_costs.json').read_text())
    holdout=set(protocol['reserved_holdout_groups'])
    validate_splits(protocol['selected'],holdout);validate_splits(old_labels,holdout)
    assert len(holdout)==73 and len(protocol['selected'])==30
    assert sha(DATA)==protocol['dataset_sha256'] and sha(MODEL)==protocol['v5_model_sha256']
    actions=dynamic_action_names(config)
    params=original.regressor.get_params()
    protected={str(p):sha(p) for p in [MODEL,DATA,SOURCE/'protocol.json',SOURCE/'results.json',
        Path('configs/research_status.json'),Path('configs/real_desktop_ml.json')]}
    protected.update({str(p):sha(p) for p in Path('dashboard').rglob('*')
        if p.is_file() and 'node_modules' not in p.parts and 'dist' not in p.parts and '__pycache__' not in p.parts})
    write(OUT/'protocol.json',{'selected':protocol['selected'],'source_protocol_sha256':sha(SOURCE/'protocol.json'),
        'actions':list(actions),'features':list(DYNAMIC_FEATURE_NAMES),'config':asdict(config),
        'tree_parameters':params,'switch_margin':original.switch_margin,'fits_allowed':1,'evaluation_runs_allowed':1,
        'final_holdout_groups':73,'holdout_evaluated':False,'independent_test':False,
        'label_completion':'Replay identical saved states; verify saved four heads; add FCFS/Priority. No workload expansion.',
        'score_bounds':'Reuse saved five-static per-workload bounds; verify current tuned MLFQ score matches saved score.',
        'budgets_seconds':{'label_workload':60,'evaluation_policy':20},'protected_sha256':protected})
    by_id={w['workload_id']:w for w in workloads};labels=[]
    # The four-head Azure artifact cannot pass the original six-head v5 loader.
    # Complete its targets at exactly the same sampled states, never invent heads.
    for index,item in enumerate(protocol['selected']):
        wid=item['workload_id'];jobs=[Process(**p) for p in by_id[wid]['processes']]
        with budget(60):
            refs=references(jobs)
            for behavior in ['MLFQ','preemptive_probe']:
                saved=[r for r in old_labels if r['workload_id']==wid and r['behavior']==behavior]
                states=_training_states(jobs,config,_policy_config(None),'MLFQ',SEED+index,
                    PreemptiveProbe() if behavior=='preemptive_probe' else None,max_states=6)
                assert len(saved)==len(states)
                for old,(state,active,dwell) in zip(saved,states):
                    assert old['features']==extract_dynamic_features(state,active,dwell)
                    assert old['time']==state.current_time and old['active']==active
                    label,costs=_counterfactual_label(state,config.epoch_ticks,_policy_config(None),actions,
                        active,dwell,config=config,references=refs)
                    np.testing.assert_allclose([costs[a] for a in ACTIONS],old['costs'],rtol=0,atol=1e-12)
                    labels.append({**old,'label':label,'costs':[costs[a] for a in actions]})
        write(ART/'decision_costs.json',labels)
        print('completed labels',wid,len(labels),flush=True)
    splits={s:[r for r in labels if r['split']==s] for s in ['train','validation','test']}
    assert [len(splits[s]) for s in splits]==[216,72,72]
    x=[[r['features'][f] for f in DYNAMIC_FEATURE_NAMES] for r in splits['train']]
    y=[r['costs'] for r in splits['train']]
    tree=DecisionTreeRegressor(**params).fit(x,y)  # Sole training run.
    model=PolicyCostModel(tree,actions,original.switch_margin)
    bundle=joblib.load(MODEL)
    metadata={**bundle['metadata'],'label_provenance':'azure_proxy_grouped_development_only',
        'selected_for_development':False,'diagnostic_only':True,'experiment':str(OUT),
        'training_groups':sorted({r['source_group'] for r in splits['train']})}
    joblib.dump({'model':model,'features':tuple(DYNAMIC_FEATURE_NAMES),'metadata':metadata},ART/'model.joblib')
    candidate=load_model(ART/'model.joblib',DYNAMIC_FEATURE_NAMES,expected_dynamic_config=config)
    assert candidate.policies==original.policies and candidate.switch_margin==0.005
    write(OUT/'frozen_model.json',{'sha256':sha(ART/'model.joblib'),'test_scheduling_accessed':False,
        'parameters':params,'training_rows':len(x),'promoted':False})
    diagnostics={s:regression(tree,rs) for s,rs in splits.items()}
    dummy={s:regression(MeanCosts(y),rs) for s,rs in splits.items()}
    write(OUT/'prediction_metrics.json',{'model':diagnostics,'mean_cost_dummy':dummy})
    rows=[]
    for item in [i for i in protocol['selected'] if i['split']=='test']:
        wid=item['workload_id'];jobs=[Process(**p) for p in by_id[wid]['processes']]
        refs=cached_references(old_results['test_rows'],wid)
        for name,model in [('Original v5',original),(NAME,candidate),('Tuned MLFQ',None)]:
            row={'workload_id':wid,'source_group':item['source_group'],
                'previous_source_group_seen':item['previous_source_group_seen'],'policy':name}
            start=time.monotonic()
            try:
                with budget(20):
                    router=run_dynamic(jobs,model,config) if model is not None else None
                    result=router.simulation if router else run_simulation(name,mlfq,jobs,quanta=(1,2,4),aging_threshold=40)
                ds=router.decisions if router else []
                row.update(status='COMPLETE',weighted_score=score_result_against_reference(result,refs),
                    avg_waiting_ms=result.avg_waiting_time,avg_response_ms=result.avg_response_time,
                    p95_response_ms=_percentile([p.response_time for p in result.process_metrics],.95),
                    avg_turnaround_ms=result.avg_turnaround_time,starvation=aggregate_fairness(result.process_metrics)['starvation_count'],
                    accepted_switches=sum(d.accepted for d in ds),decision_reviews=len(ds),
                    reasons=dict(Counter(d.reason for d in ds)),decision_p99_ms=router.transition_p99_ms if router else None)
                if name=='Tuned MLFQ':
                    saved=next(r for r in old_results['test_rows'] if r['workload_id']==wid and r['policy']==name)
                    assert abs(saved['weighted_score']-row['weighted_score'])<1e-12
            except TimeoutError as error:
                row.update(status='TIMEOUT',reason=str(error))
            row['wall_seconds']=time.monotonic()-start;rows.append(row)
            write(OUT/'workload_results.json',rows)
            if row['status']=='TIMEOUT':raise TimeoutError('Stopped after first evaluation timeout; partial findings saved')
        print('evaluated',wid,flush=True)
    summary={name:{key:mean(r[key] for r in rows if r['policy']==name) for key in
        ['weighted_score','avg_waiting_ms','avg_response_ms','p95_response_ms','avg_turnaround_ms','starvation']}
        for name in ['Original v5',NAME,'Tuned MLFQ']}
    paired={}
    for baseline in ['Original v5','Tuned MLFQ']:
        left=[r for r in rows if r['policy']==NAME];right=[r for r in rows if r['policy']==baseline]
        paired[baseline]={k:paired_bootstrap_ci([a[k]-b[k] for a,b in zip(left,right)])
            for k in ['weighted_score','p95_response_ms','starvation']}
    coverage={n:{'completed_workloads':sum(r['status']=='COMPLETE' for r in rows if r['policy']==n),
        'timeouts':sum(r['status']=='TIMEOUT' for r in rows if r['policy']==n),
        'accepted_switches':sum(r['accepted_switches'] for r in rows if r['policy']==n)} for n in summary}
    latency=max(r['decision_p99_ms'] for r in rows if r['policy']==NAME)
    gates={'strict_score_improvement_vs_tuned':paired['Tuned MLFQ']['weighted_score']['ci_high']<0,
        'p95_nonregression':paired['Tuned MLFQ']['p95_response_ms']['ci_high']<=0,
        'starvation_nonregression':paired['Tuned MLFQ']['starvation']['mean']<=0,
        'routing_p99_lt_10ms':latency<10,'complete_coverage':len(rows)==18}
    assert all(sha(Path(p))==h for p,h in protected.items())
    write(OUT/'results.json',{'summary':summary,'coverage':coverage,'prediction_metrics':diagnostics,
        'mean_cost_dummy':dummy,'paired_differences_95ci':paired,'gates':gates,'promoted':False,
        'routing_p99_max_ms':latency,'protected_files_verified':len(protected),'holdout_evaluated':False})
    report=['# Exact-v5 Azure retraining: one development experiment','',
        'Azure Functions 2019 reconstructed arrivals and wall-clock CPU-demand proxies; simulator evidence, not Linux measurements.',
        '30 fixed provenance groups: train 18/216 states, validation 6/72, test 6/72. Test has 115 processes; two test groups were previously inspected. Entire comparison is non-independent development evidence. Final 73-group holdout untouched.',
        'Original v5 six outputs, 19 features, depth 3, leaf 10, seed 9701; margin .005 and controller unchanged. Missing FCFS/Priority labels completed at identical saved states; all four existing target heads verified. One fit, no tuning. Mean-cost dummy uses training means.',
        '', '## Scheduling means','Policy | Score | Wait ms | Response ms | P95 ms | Turnaround ms | Starvation | Accepted total','---|---:|---:|---:|---:|---:|---:|---:']
    for n,m in summary.items():report.append(n+' | '+' | '.join(f'{m[k]:.8f}' for k in m)+f" | {coverage[n]['accepted_switches']}")
    report+=['','## Regression (six outputs pooled)','Split | MAE | RMSE | R² | Dummy MAE | Dummy RMSE | Dummy R²','---|---:|---:|---:|---:|---:|---:']
    for s,m in diagnostics.items():report.append(s+' | '+' | '.join(f'{d[k]:.10g}' for d in [m,dummy[s]] for k in ['mae','rmse','r_squared']))
    report+=['',f'Coverage: {coverage}. Maximum candidate routing P99: {latency:.6f} ms.',
        f'Frozen score/P95/starvation/latency/coverage checks: {gates}. No promotion; tuned MLFQ remains recommended.',
        'Paired confidence intervals and per-workload reasons are saved in results.json and workload_results.json. All protected hashes verified. No frontend changes.']
    (OUT/'REPORT.md').write_text('\n'.join(report)+'\n')


if __name__=='__main__':
    try:run()
    except (TimeoutError,AssertionError,ValueError) as error:
        write(OUT/'BLOCKED.json',{'reason':str(error),'partial_findings_preserved':True})
        raise
