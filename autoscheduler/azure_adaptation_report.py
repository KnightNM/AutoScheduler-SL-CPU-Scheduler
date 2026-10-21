"""Read-only report/dashboard export for the single frozen Azure experiment."""
from collections import Counter,defaultdict
import json
from pathlib import Path
from statistics import mean
from time import perf_counter_ns
import joblib
import numpy as np

from autoscheduler.azure_adaptation import OUTPUT,ARTIFACTS,ACTIONS,DYNAMIC_FEATURE_NAMES
from autoscheduler.azure_generalization import write,sha


def summarize():
    protocol=json.loads((OUTPUT/'protocol.json').read_text())
    if (OUTPUT/'BLOCKED.json').exists():
        block=json.loads((OUTPUT/'BLOCKED.json').read_text())
        result={'status':'BLOCKED','training_occurred':False,'reason':block['reason'],
                'protocol':str(OUTPUT/'protocol.json'),'promoted':False,'holdout_evaluated':False}
        write(OUTPUT/'dashboard.json',result)
        (OUTPUT/'REPORT.md').write_text('# Azure adaptation: blocked\n\n'+block['reason']+'\n\nNo model promoted. Existing v5/tuned MLFQ recommendation preserved. See protocol, labeling outcomes and feasibility evidence.\n')
        return
    raw=json.loads((OUTPUT/'results.json').read_text());rows=raw['test_rows'];grouped=defaultdict(dict)
    for r in rows:
        r['rejected_switch_reviews']=sum(v for k,v in r.get('reasons',{}).items() if k in {
            'cost_margin','dwell_blocked','arrival_risk','first_service_protection','low_confidence','response_dwell_blocked'})
        r['same_policy_holds']=r.get('reasons',{}).get('same_policy',0)
        grouped[r['workload_id']][r['policy']]=r
    policies=list(dict.fromkeys(r['policy'] for r in rows))
    common=[wid for wid,v in grouped.items() if len(v)==len(policies) and all(r['status']=='COMPLETE' and r['weighted_score'] is not None for r in v.values())]
    keys=['weighted_score','avg_waiting_ms','avg_response_ms','p95_response_ms','avg_turnaround_ms',
          'utilization_fraction','throughput_jobs_per_ms','starvation','context_switches','accepted_switches','nonaccepted_reviews','decision_examples','decision_p99_ms','rejected_switch_reviews','same_policy_holds']
    metrics={p:{key:mean([grouped[wid][p][key] for wid in common if grouped[wid][p].get(key) is not None])
                if any(grouped[wid][p].get(key) is not None for wid in common) else None for key in keys} for p in policies}
    counts={s:{**raw['counts'][s],
        'selected_workloads':sum(w['split']==s for w in protocol['selected']),
        'selected_processes':sum(w['processes'] for w in protocol['selected'] if w['split']==s),
        'previously_inspected_source_groups':sum(w['split']==s and w['previous_source_group_seen'] for w in protocol['selected'])}
        for s in ['train','validation','test']}
    protected=json.loads((OUTPUT/'preserved_sha256.json').read_text())
    assert all(sha(p)==digest for p,digest in protected.items())
    selected_groups={w['source_group'] for w in protocol['selected']}
    assert not selected_groups.intersection(protocol['reserved_holdout_groups'])
    label_rows=json.loads((ARTIFACTS/'decision_costs.json').read_text())
    target=np.array([r['costs'] for r in label_rows]);benefits=target[:,0]-target.min(axis=1)
    model=joblib.load(ARTIFACTS/'model.joblib')['model']
    leaves=model.regressor.tree_.value[model.regressor.tree_.children_left==-1].reshape(-1,len(ACTIONS))
    labels={'decision_states':len(label_rows),'reference_action_counts':dict(Counter(r['label'] for r in label_rows)),
        'largest_reference_switch_benefit':float(benefits.max()),'rows_meeting_frozen_margin':int((benefits>=.005).sum()),
        'frozen_switch_margin':.005,'maximum_leaf_predicted_advantage':float((leaves[:,0]-leaves.min(axis=1)).max())}
    write(OUTPUT/'label_diagnostics.json',labels)
    timing_path=OUTPUT/'inference_latency.json'
    if not timing_path.exists():
        model.predict([[label_rows[0]['features'][f] for f in DYNAMIC_FEATURE_NAMES]])
        timings=[]
        for row in label_rows:
            if row['split']=='test':
                matrix=[[row['features'][f] for f in DYNAMIC_FEATURE_NAMES]]
                started=perf_counter_ns();model.predict(matrix);timings.append((perf_counter_ns()-started)/1e6)
        write(timing_path,{'scope':'One saved-test-row batch-one predict call per state after one warmup; no feature extraction or guards; standalone Python microbenchmark, not kernel time',
            'samples':len(timings),'mean_ms':mean(timings),'p99_ms':float(np.percentile(timings,99))})
    result={**raw,'status':'EXPERIMENTAL_NOT_APPROVED','dataset':'Azure Functions 2019 revision 2 · reconstructed proxy simulations',
        'counts':counts,'common_test_workloads':len(common),'test_workloads_selected':len(grouped),
        'common_test_processes':sum(w['processes'] for w in protocol['selected'] if w['workload_id'] in common),
        'test_metrics':metrics,'timeouts':[r for r in rows if r['status']!='COMPLETE'],
        'test_prior_exposure_note':'Internal grouped development test; prior source exposure is flagged. Not an untouched final test. The separate 73 provenance groups remain untouched.',
        'regression_units':'Dimensionless weighted-score delta versus tuned MLFQ continuation; MAE/RMSE over four decision-action cost outputs, R² pooled over decision-action pairs.',
        'limitations':'Metadata-capped sample: no high-contention workload fits caps; no measured I/O or OS ready queues. Wall-clock duration proxies are not observed CPU bursts. No Linux-kernel performance claim.',
        'source':str(OUTPUT/'results.json'),'report':str(OUTPUT/'REPORT.md'),
        'recommendation':'Keep tuned static MLFQ (1,2,4), aging 40. Preserve v5 as historical experimental baseline; do not promote this Azure candidate.',
        'protected_files_unchanged':len(protected),'reserved_holdout_groups':len(protocol['reserved_holdout_groups'])}
    result['label_diagnostics']=labels
    result['inference_latency']=json.loads(timing_path.read_text())
    result['test_transition_totals']={p:{key:sum(grouped[wid][p].get(key,0) for wid in common)
        for key in ['accepted_switches','rejected_switch_reviews','same_policy_holds']} for p in ['Azure tree','Dynamic v5']}
    exposure={w['workload_id']:w['previous_source_group_seen'] for w in protocol['selected']}
    better_p95=[wid for wid in common if grouped[wid]['Azure tree']['p95_response_ms']<grouped[wid]['Dynamic v5']['p95_response_ms']]
    result['p95_improvement_vs_v5_workloads']=[{'workload_id':wid,'previous_source_group_seen':exposure[wid]} for wid in better_p95]
    coverage={'cohorts':dict(Counter(w['cohort'] for w in protocol['selected'])),
        'heterogeneous_proxy_bursts':sum(w['burst_cv']>0 for w in protocol['selected']),
        'sustained_span_proxy':sum(w['arrival_span_ms']>=.7*w['total_cpu_proxy_ms']/w['cpu_per_exposure'] for w in protocol['selected']),
        'interarrival_cv_at_least_one':sum((w['interarrival_cv'] or 0)>=1 for w in protocol['selected']),
        'high_contention':sum(w['arrival_work_pending_fraction']>=.5 for w in protocol['selected']),
        'scope':'Descriptive metadata coverage after frozen selection; reconstructed arrival shape, not observed OS bursts; no outcome-based resampling'}
    result['coverage']=coverage
    write(OUTPUT/'dashboard.json',result)
    lines=['# Azure-adapted policy-cost tree: one controlled development experiment','',
        '**Reconstructed real-source workload simulations, not Linux kernel measurements. No model promoted.**','',
        '## Protocol and data','',
        'Microsoft Azure Functions 2019 revision 2, CC-BY; Mohammad Shahrad et al., “Serverless in the Wild,” ATC 2020. '
        'Original cleaned input: 510 workloads/520,408 reconstructed jobs. No source record, scheduler parameter, objective weight or historical result changed. '
        'One tick = 1 ms. Daily mean wall-clock durations remain CPU-demand proxies; within-minute arrivals are reconstructed.','',
        'Seed 20261022. Select complete workloads by metadata, before outcomes: 5–100 processes; '
        'low/mixed-low total proxy work <=20,000 ms, moderate <=100,000 ms, high <=200,000 ms. '
        'One workload per connected owner/app/function component across all days/hours/snapshots. '
        'Selected 30 groups: 24 low, 2 mixed-low, 4 moderate. No high-contention group satisfies caps. '
        'The 73 separately reserved groups are disjoint from every selected source and never evaluated. '
        'This cap-limited experiment cannot establish broad Azure or high-contention generalization.','',
        'Descriptive metadata coverage (not additional selection/tuning): '+json.dumps(coverage)+'.','',
        'Protocol and split IDs were saved before labeling/fitting. Three representative reference+finite-label benchmarks each passed the fixed 10-second budget (`feasibility.json`). '
        'Labeling has a predeclared 60-second whole-workload cap; every timeout/empty workload remains in `label_outcomes.json`, with no replacement. '
        'Evaluation retains every 20-second per-policy timeout and never renormalizes missing references.','',
        '## Targets, safety and model selection','',
        'Nineteen inputs come from existing observed-state extraction at actual legal dispatch boundaries. '
        'Each MLFQ or safeguarded preemptive-exploration trajectory contributes up to six uniform reservoir states. '
        'Bounded sampling avoids copying every historical timeline and does not change trajectory policy or timestamps. '
        'Labels use the existing feasible-action counterfactual: hold through minimum dwell until the next safe review, '
        'then tuned MLFQ to completion; score differences use the same five frozen eligible-static bounds. '
        'Future simulator outcomes belong only to targets; no future arrivals, remaining burst or oracle features enter inference.','',
        'Eligible learned actions: **No Switch, MLFQ, RR2, Priority-RR2**. Non-preemptive FCFS/Priority departures are excluded before argmin, '
        'rather than changing their scheduler semantics. Fixed static FCFS/Priority remain comparators. '
        'Confidence, .005 benefit margin, first-service/arrival protection, fallback, 20-ms dwell and safe return logic remain unchanged. '
        'Priority-RR retains its inherited 1-ms context-switch cost; other policies retain zero. '
        'The tiny deterministic test reproduces the original Priority response of 60 ticks and verifies a preemptive action limits that example to <=2.','',
        'Two trees only: depth 3 or 5, leaf 5, seed fixed. Fit training groups only. '
        'Choose by validation safety eligibility, then realized scheduling score; no classification-accuracy selection. '
        'No forest, refit, test-driven retuning or final-holdout use. `frozen_candidate.json` and model hash precede test prediction/scoring.','',
        f"Frozen candidate: **{raw['chosen']}**. Development-selected primary static: **{raw['primary_static']}**.",'',
        '## Prediction metrics','',
        result['regression_units']+' R² is not classification accuracy. Constant targets yield undefined R², never an invented perfect value. '
        'Two zero/reference output heads can affect pooled R²; compare the mean-cost dummy and realized schedules rather than relying on R² alone.','',
        '| Split | Selected groups / labeled groups | Processes selected | Decision rows | MAE | RMSE | R² | Mean-cost dummy MAE / RMSE / R² |',
        '|---|---:|---:|---:|---:|---:|---:|---|']
    def fmt(v):return 'Undefined' if v is None else f'{v:.8f}'
    for split,m in raw['prediction_metrics'].items():
        c=counts[split];d=raw['dummy_metrics'][split]
        lines.append(f"| {split} | {c['selected_workloads']} / {c['groups']} | {c['selected_processes']} | {m['decision_rows']} | "+' | '.join(fmt(m[k]) for k in ['mae','rmse','r_squared'])+' | '+' / '.join(fmt(d[k]) for k in ['mae','rmse','r_squared'])+' |')
    lines+=['','Strict/tie-aware action agreement and a fixed No Switch reference are in `results.json`; these are reference-action agreement, not classifier accuracy. '
        'All observed features/actual costs are saved locally in `artifacts/dynamic_azure_adapted_20261020/decision_costs.json`; '
        'test numerical predictions are saved separately. Grouped rows are correlated; the group—not individual rows—is the independent split unit.','',
        f"Reference actions: {labels['reference_action_counts']}. Largest feasible switch benefit among all {len(label_rows)} sampled states: "
        f"{labels['largest_reference_switch_benefit']:.10f}, versus frozen margin .005; no row clears the margin. "
        f"The frozen tree’s largest leaf-predicted advantage is {labels['maximum_leaf_predicted_advantage']:.10f}, also below the margin. "
        'Consequently this tree cannot accept a learned departure with the existing safeguards. Tiny absolute errors are partly a consequence '
        'of nearly-zero targets, not proof of useful adaptation. A larger averaging forest cannot fix the observed absence of sufficiently '
        'valuable eligible actions. The negative validation R² and dummy baseline are retained, not hidden.','',
        f"Internal test: {counts['test']['selected_workloads']} groups, of which {counts['test']['previously_inspected_source_groups']} were previously inspected. "
        'They are separate from this fit’s train/validation groups, but the full set is not an untouched independent test.','',
        f"P95 improvements versus v5 occur in: {result['p95_improvement_vs_v5_workloads']}. "
        'The observed improvement is confined to a previously inspected source; it is not new independent response-tail evidence.','',
        '## Identical internal-test scheduling workloads','',
        f"{len(common)}/{len(grouped)} workloads completed every policy; {result['common_test_processes']} processes in that common subset. "
        f"{len(result['timeouts'])} policy timeouts retained. The following means use only common complete inputs; missing coverage is not success.",'',
        '| Policy | Score | Waiting ms | Response ms | P95 ms | Turnaround ms | Utilization | Jobs/ms | Starvation | Context switches | Accepted / nonaccepted reviews |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|']
    for p,m in metrics.items():
        lines.append('| '+p+' | '+' | '.join(fmt(m[k]) for k in keys[:9])+f" | {fmt(m['accepted_switches'])} / {fmt(m['nonaccepted_reviews'])} |")
    lines+=['','Context switches are PID transitions; accepted policy transitions are distinct. Nonaccepted reviews include same-policy holds and blocked proposals; reasons are saved per workload. '
        'Routing P99 includes observed feature/model/guard work; static inference latency is unmeasured. No generic adaptive reconfiguration charge is added.','',
        'Exact test transition totals (same-policy holds separated from rejected switching reviews): '+json.dumps(result['test_transition_totals'])+'.','',
        f"Pure batch-one model inference: {result['inference_latency']['samples']} saved test states; "
        f"mean {result['inference_latency']['mean_ms']:.6f} ms, P99 {result['inference_latency']['p99_ms']:.6f} ms. "
        'This one-pass microbenchmark is separate from routing P99. Python inference time does not advance simulated workload time; '
        'it is not charged into scheduling throughput/utilization and is not Linux controller timing.','',
        '## Frozen gates and uncertainty','',
        'Paired workload percentile bootstrap, 10,000 draws, seed 2027, one workload per provenance group. '
        'Tiny, capped, previously examined development sources make intervals exploratory, not final generalization evidence.','',
        '```json',json.dumps({'versus_primary':raw['test_vs_primary'],'versus_tuned':raw['test_vs_tuned']},indent=2),'```','',
        result['recommendation'],'',result['limitations'],'',
        f"Model: `{raw['model_path']}`, SHA256 `{raw['model_sha256']}`. "
        f"All {len(protected)} pre-existing protected report/model/data/configuration hashes match. "
        'Verification is saved separately in `verification.json`. No push/merge.','',
        'Reproduce only with fresh versioned OUTPUT/ARTIFACTS paths: `.venv/bin/python -m autoscheduler.azure_adaptation`; '
        'read saved results with `.venv/bin/python -m autoscheduler.azure_adaptation_report`. Completed experiments refuse overwrite.']
    (OUTPUT/'REPORT.md').write_text('\n'.join(lines)+'\n')


if __name__=='__main__':summarize()
