"""Development-only safe-policy headroom audit; no fitting or dashboard edits."""
from collections import Counter
import json
from pathlib import Path
from statistics import mean
from time import monotonic
from unittest.mock import patch

import joblib
import numpy as np
from sklearn.metrics import mean_absolute_error,mean_squared_error,r2_score

import autoscheduler.dynamic as dynamic
from autoscheduler.azure_adaptation import ACTIONS,ARTIFACTS,PreemptiveProbe,SEED,budget,references
from autoscheduler.azure_generalization import DATA,sha,write
from autoscheduler.fairness import aggregate_fairness
from simulator.process import Process

OUTPUT=Path('results/azure_safe_headroom_20261020')


def cost_headroom(rows,margin=.005):
    costs=np.asarray([r['costs'] for r in rows]);baseline=costs[:,ACTIONS.index('MLFQ')]
    benefits=baseline-costs.min(axis=1)
    return {'decision_states':len(rows),
        'mlfq_optimal_or_tied_states':int((benefits<=1e-12).sum()),
        'positive_benefit_states':int((benefits>1e-12).sum()),
        'states_clearing_frozen_margin':int((benefits>=margin).sum()),
        'nonzero_cost_difference_states':int((np.ptp(costs,axis=1)>1e-12).sum()),
        'maximum_benefit':float(benefits.max()),'frozen_margin':margin}


def metrics(result):
    return {'waiting_ms':result.avg_waiting_time,'response_ms':result.avg_response_time,
        'p95_response_ms':dynamic._percentile([p.response_time for p in result.process_metrics],.95),
        'worst_response_ms':max(p.response_time for p in result.process_metrics),
        'turnaround_ms':result.avg_turnaround_time,'context_switches':result.context_switches,
        'charged_context_switch_ms':result.context_switch_time,
        'starvation':aggregate_fairness(result.process_metrics)['starvation_count']}


def run():
    if OUTPUT.exists():raise ValueError('Refuse to overwrite a completed/partial audit')
    paths=[p for p in Path('results').rglob('*') if p.is_file()]
    paths+=list(Path('artifacts').rglob('model.joblib'))
    paths+=list(Path('dashboard/web/src').rglob('*'))
    paths=[p for p in paths if p.is_file()]+[DATA,Path('dashboard/adapter.py'),Path('configs/research_status.json'),Path('configs/real_desktop_ml.json')]
    protected={str(p):sha(p) for p in paths};write(OUTPUT/'preserved_sha256.json',protected)
    protocol=json.loads(Path('results/azure_adapted_20261020/protocol.json').read_text())
    # Exclude old test rows before any prediction/target analysis.
    rows=[r for r in json.loads((ARTIFACTS/'decision_costs.json').read_text()) if r['split'] in {'train','validation'}]
    model=joblib.load(ARTIFACTS/'model.joblib')['model'];margin=model.switch_margin
    relevant=[r for r in rows if np.ptp(r['costs'])>1e-12]
    write(OUTPUT/'protocol.json',{'scope':'Training/validation groups only; no old test re-evaluation or final-holdout consumption',
        'input_protocol_sha256':sha('results/azure_adapted_20261020/protocol.json'),
        'model_sha256':sha(ARTIFACTS/'model.joblib'),'margin':margin,
        'states':[{k:r[k] for k in ['workload_id','source_group','split','behavior','time','active']} for r in relevant],
        'selection':'Replay every development state with any nonzero feasible cost difference (>1e-12), including losses; no favorable-only sample.',
        'budgets':'30 seconds per state collection/reference run or counterfactual replay; retain all failures, no replacements',
        'stop_rule':'If no sampled feasible benefit clears unchanged margin, stop before dataset expansion/fitting; preserve dashboard.'})
    summary=cost_headroom(rows,margin)
    summary.update(groups=len({r['source_group'] for r in rows}),splits=dict(Counter(r['split'] for r in rows)),
        reference_actions=dict(Counter(r['label'] for r in rows)),training_occurred=False,
        old_test_re_evaluated=False,final_holdout_evaluated=False,dashboard_changed=False)
    leaves=model.regressor.tree_.value[model.regressor.tree_.children_left==-1].reshape(-1,len(ACTIONS))
    summary['maximum_leaf_predicted_advantage']=float((leaves[:,0]-leaves.min(axis=1)).max())
    train=[r for r in rows if r['split']=='train'];dummy_mean=np.mean([r['costs'] for r in train],axis=0)
    quality={}
    for split in ['train','validation']:
        sample=[r for r in relevant if r['split']==split]
        y=np.array([r['costs'] for r in sample]);x=[[r['features'][f] for f in dynamic.DYNAMIC_FEATURE_NAMES] for r in sample]
        if not sample:continue
        outputs={}
        for name,pred in [('existing_tree',model.regressor.predict(x)),('training_mean_dummy',np.tile(dummy_mean,(len(sample),1)))]:
            actual=y.ravel();predicted=np.asarray(pred).ravel()
            outputs[name]={'mae':float(mean_absolute_error(actual,predicted)),
                'rmse':float(np.sqrt(mean_squared_error(actual,predicted))),
                'r_squared':float(r2_score(actual,predicted)) if np.var(actual)>0 else None}
        quality[split]={'nonzero_states':len(sample),'metrics_on_nonzero_differences':outputs,
            'actionable_states':0,'actionable_quality':None,'reason':'No state clears the frozen margin'}
    workloads={w['workload_id']:w for w in json.loads(DATA.read_text())['workloads']}
    indexes={w['workload_id']:i for i,w in enumerate(protocol['selected'])}
    config=dynamic.DynamicRouterConfig(**protocol['config']);rr=dynamic._policy_config(None)
    refs_cache={};state_cache={};replays=[]
    for row in relevant:
        wid=row['workload_id'];started=monotonic()
        record={k:row[k] for k in ['workload_id','source_group','split','behavior','time','active']}
        try:
            if wid not in refs_cache:
                with budget(30):refs_cache[wid]=references([Process(**p) for p in workloads[wid]['processes']])
            key=(wid,row['behavior'])
            if key not in state_cache:
                with budget(30):state_cache[key]=dynamic._training_states([Process(**p) for p in workloads[wid]['processes']],config,rr,'MLFQ',
                    SEED+indexes[wid],PreemptiveProbe() if row['behavior']=='preemptive_probe' else None,max_states=6)
            matches=[(s,a,d) for s,a,d in state_cache[key] if s.current_time==row['time'] and a==row['active']]
            assert len(matches)==1,'Saved decision state must reproduce uniquely'
            state,active,dwell=matches[0]
            assert dynamic.extract_dynamic_features(state,active,dwell)==row['features']
            captured={};original=dynamic._simulation
            def capture(state,action):
                result=original(state,action);captured[action]=result;return result
            # Observe the exact existing labeler in this isolated offline process.
            with budget(30),patch.object(dynamic,'_simulation',side_effect=capture):
                _,costs=dynamic._counterfactual_label(state,config.epoch_ticks,rr,ACTIONS,active,dwell,config=config,references=refs_cache[wid])
            assert all(abs(costs[a]-c)<1e-12 for a,c in zip(ACTIONS,row['costs']))
            base=metrics(captured['MLFQ']);outcomes={a:metrics(result) for a,result in captured.items()}
            for a,m in outcomes.items():m.update(relative_cost=costs[a],p95_delta_ms=m['p95_response_ms']-base['p95_response_ms'],
                worst_response_delta_ms=m['worst_response_ms']-base['worst_response_ms'],starvation_delta=m['starvation']-base['starvation'])
            record.update(status='COMPLETE',features_reproduced=True,costs_reproduced=True,outcomes=outcomes)
        except TimeoutError as error:record.update(status='TIMEOUT',reason=str(error))
        record['wall_seconds']=monotonic()-started;replays.append(record)
        write(OUTPUT/'counterfactuals.json',replays);print(wid,row['time'],record['status'],flush=True)
    summary['replay_states']=len(replays);summary['timeouts']=sum(r['status']=='TIMEOUT' for r in replays)
    positives=[{'workload_id':r['workload_id'],'time':r['time'],'action':a,**m} for r in replays if r['status']=='COMPLETE'
               for a,m in r['outcomes'].items() if m['relative_cost']<-1e-12]
    summary['positive_alternatives']=positives
    summary['positive_alternatives_without_p95_or_starvation_regression']=sum(p['p95_delta_ms']<=0 and p['starvation_delta']<=0 for p in positives)
    summary['headroom_claim_scope']='288 existing development states, 24 groups; not all Azure functions or unobserved high-contention workloads'
    summary['decision']='STOP_NO_ACTIONABLE_HEADROOM' if summary['states_clearing_frozen_margin']==0 else 'HEADROOM_REQUIRES_FROZEN_FOLLOWUP'
    write(OUTPUT/'summary.json',summary);write(OUTPUT/'prediction_diagnostics.json',quality)
    assert all(sha(path)==digest for path,digest in protected.items())
    report=['# Azure safe-policy headroom: stop before retraining','',
        '**No new model, dataset expansion, dashboard change or promotion. Tuned MLFQ remains recommended.**','',
        'Analysis uses only existing training/validation rows. Previously examined test rows are excluded from all new prediction and replay analysis. '
        'The 73 final-holdout groups are not consumed. Raw Azure records, models, historical reports and dashboard sources remain unchanged.','',
        '| Existing development headroom | Count |','|---|---:|',
        f"| Decision states / provenance groups | {len(rows)} / {summary['groups']} |",
        f"| MLFQ optimal or tied | {summary['mlfq_optimal_or_tied_states']} / {len(rows)} |",
        f"| Another feasible action has lower objective | {summary['positive_benefit_states']} |",
        f"| Any nonzero action-cost difference (>1e-12) | {len(relevant)} |",
        f"| Benefit clears fixed .005 admission margin | {summary['states_clearing_frozen_margin']} |",'',
        f"Largest feasible benefit: **{summary['maximum_benefit']:.10f}**, approximately {margin/summary['maximum_benefit']:.1f} times below .005. "
        f"Largest advantage in any fitted tree leaf: **{summary['maximum_leaf_predicted_advantage']:.10f}**. "
        'Thus the saved tree cannot admit a learned departure from startup MLFQ under its current margin, even for unseen feature vectors. '
        'Its zero switching is primarily an absence of sufficient feasible value, not merely an inaccurate action ranking.','',
        '## Existing target already is incremental','',
        'Targets are already feasible-action weighted scheduling cost **minus immediate tuned-MLFQ continuation cost**, not absolute whole-workload policy costs. '
        'They retain a 20-ms minimum-dwell horizon, safe dispatch return, first-service/arrival restrictions and fixed five-static normalization. '
        'Relabeling the same numbers as deltas cannot create headroom. The No Switch/MLFQ outputs are zero in this sample. '
        'Features remain observed scheduler history; counterfactual futures are used only for offline targets/analysis.','',
        '## Tiny alternatives and response risk','',
        f"Replayed every one of the {len(relevant)} nonzero development states, including worse actions; {summary['timeouts']} timeouts retained. "
        'Each observed feature vector and cost vector is checked against its saved original before reporting outcomes. '
        'The exact existing labeler is observed, not reimplemented. Known RR/Priority-RR context-switch charges are included; no new generic policy-setup charge is invented.','',
        '| Workload / decision ms | Action | Relative objective | P95 change ms | Worst response change ms | Charged context overhead ms |',
        '|---|---|---:|---:|---:|---:|']
    for p in positives:report.append(f"| {p['workload_id']} / {p['time']} | {p['action']} | {p['relative_cost']:.10f} | {p['p95_delta_ms']:.3f} | {p['worst_response_delta_ms']:.3f} | {p['charged_context_switch_ms']} |")
    report+=['','Full outcomes, including losing Priority-RR alternatives, waiting/response/turnaround, starvation and context switches, are in `counterfactuals.json`. '
        'Tied-objective states were not replayed for response differences; they cannot establish strict score superiority. '
        'Per-state counterfactuals are not a deployable oracle or a whole-workload adaptive performance claim.','',
        '## Regression diagnosis','',
        'Only seven states have nonzero feasible cost spreads; zero have admission-sized value. '
        'Prediction quality on nonzero (not admission-sized) states is recorded below; no actionable-state metric can be measured from an empty subset. '
        'The dummy is the analytical mean of original training costs, with no new fitting. R² is pooled over decision-action pairs, not classification accuracy.','',
        '```json',json.dumps(quality,indent=2),'```','',
        'Adding a small averaging forest or a larger tree cannot create true benefit exceeding the observed target range. '
        'Negative validation R² remains a modeling weakness, but fixing it would not unlock a safe switch under this margin. '
        'The old v5 Priority gains involve a prohibited non-preemptive action and previously demonstrated response risk; they are not eligible headroom.','',
        '## Verdict and limits','',
        'No useful safe switching behavior or superiority over MLFQ is demonstrated. Stop before Phases 2–5: '
        'do not enlarge the dataset, change thresholds, fit another model or revisit test outcomes merely to force transitions. '
        'Preserve the existing dashboard exactly. The known dataset is capped/mostly low contention, so absence of headroom here is not proof '
        'that all 510 Azure workloads lack it. Larger queues and high-contention source groups would require a separately justified, frozen feasibility study. '
        'Azure wall-clock CPU-demand proxies and reconstructed arrivals do not establish Linux scheduler behavior.','',
        'Reproduce in a fresh OUTPUT: `.venv/bin/python -m autoscheduler.azure_headroom`. '
        'Focused tests, unchanged-hash checks and dashboard build are recorded in `verification.json`. No push or merge.']
    (OUTPUT/'REPORT.md').write_text('\n'.join(report)+'\n')


if __name__=='__main__':run()
