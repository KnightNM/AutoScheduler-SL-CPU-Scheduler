"""One frozen Azure development safety audit; no fitting or active-model changes."""
from collections import Counter
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import random
import signal
from statistics import mean
import time

from autoscheduler.azure_generalization import DATA, MODEL, characteristics, load, sha, write
from autoscheduler.dynamic import DYNAMIC_POLICY_NAMES, _percentile, run_dynamic
from autoscheduler.evaluation import DEPLOYABLE_ALGORITHMS, score_result_against_reference
from autoscheduler.experiments import paired_bootstrap_ci
from autoscheduler.fairness import aggregate_fairness
from scheduler.mlfq import mlfq
from simulator.process import Process
from simulator.simulator import run_simulation

OUTPUT = Path('results/real_source_dynamic_review_20261020')
PREVIOUS = Path('results/dynamic_azure_generalization')


class NonPreemptiveAdmissionGuard:
    """Experimental veto without a validated bound on nonpreemptive dispatch.

    This is action eligibility, not a learned burst predictor. The original
    fitted model, observed features, dwell and runtime safety rules are unchanged.
    """
    def __init__(self, model):
        self.model = model
        self.raw_actions = []
        self.veto_count = 0

    def predict(self, matrix):
        actions = self.model.predict(matrix)
        self.raw_actions.extend(actions)
        self.veto_count += sum(a in {'FCFS', 'Priority'} for a in actions)
        return ['No Switch' if a in {'FCFS', 'Priority'} else a for a in actions]

    def switch_allowed(self, features, active, selected):
        return selected != active and self.model.switch_allowed(features, active, selected)


def run():
    if OUTPUT.exists():
        raise ValueError('Use a new versioned output path; never overwrite this audit')
    protected_paths = [p for p in Path('results').rglob('*') if p.is_file()]
    protected_paths += list(Path('artifacts').rglob('model.joblib'))
    protected_paths += [DATA, Path('configs/research_status.json'), Path('configs/real_desktop_ml.json'),
                        Path('autoscheduler/dynamic.py'), Path('simulator/engine.py')]
    protected = {str(p): sha(p) for p in protected_paths}
    write(OUTPUT / 'preserved_sha256.json', protected)
    workloads, model, config = load()
    frozen = json.loads((PREVIOUS / 'selection_manifest.json').read_text())
    old = json.loads(Path('results/azure_external_pilot/selection.json').read_text())
    excluded = set(frozen['holdout_groups']) | {w['source_group'] for w in frozen['selected']}
    excluded |= {frozen['all_source_groups'][w['workload_id']] for w in old}
    rng = random.Random(20261021)
    selected = []; used = set(); pools = {}
    for name, lo, hi, count in [('low', 0, .05, 4), ('medium', .05, .5, 2), ('high', .5, 1.01, 2)]:
        pool = []
        for w in workloads:
            group = frozen['all_source_groups'][w['workload_id']]
            if group in excluded or not 5 <= len(w['processes']) <= 100:
                continue
            c = characteristics(w)
            if c['total_cpu_proxy_ms'] <= 500000 and lo <= c['arrival_work_pending_fraction'] < hi:
                pool.append((w, group, c))
        pool.sort(key=lambda x: x[0]['workload_id']); rng.shuffle(pool)
        taken = 0
        for w, group, c in pool:
            if group in used:
                continue
            selected.append({'workload_id': w['workload_id'], 'source_group': group,
                             'stratum': name, 'cohort': w['cohort'], **c})
            used.add(group); taken += 1
            if taken == count:
                break
        pools[name] = {'eligible_workloads': len(pool), 'requested': count, 'selected': taken}
    protocol = {'seed': 20261021, 'scope': 'Fresh provenance-disjoint DEVELOPMENT safety audit; not the final holdout',
                'rules': 'ID-sorted pools shuffled once; 5–100 jobs, <=500000 ms total proxy work; one workload per function component; no outcome selection.',
                'pools': pools, 'selected': selected, 'excluded_groups': sorted(excluded),
                'reserved_holdout_consumed': False, 'timeout_seconds_per_policy': 20,
                'candidate': 'nonpreemptive-admission-v1', 'v5_model': str(MODEL), 'model_sha256': sha(MODEL),
                'candidate_rule': 'Veto FCFS/Priority proposals as No Switch without a validated nonpreemptive dispatch bound; preserve every existing safety rule.',
                'training': False, 'config': asdict(config), 'score_references': list(DEPLOYABLE_ALGORITHMS),
                'missing_coverage': 'No fresh high-contention provenance groups meet the frozen size/CPU caps; record zero, do not reuse holdout or replace after outcomes.'}
    write(OUTPUT / 'protocol.json', protocol)  # Freeze before any policy outcomes.
    by_id = {w['workload_id']: w for w in workloads}
    rows = []; decisions = []
    def expired(*_):
        raise TimeoutError('Fixed 20-second per-policy budget; no replacement')
    previous_signal = signal.signal(signal.SIGALRM, expired)
    try:
        for item in selected:
            jobs = [Process(**p) for p in by_id[item['workload_id']]['processes']]
            results = {}; batch = []
            for policy in [*DEPLOYABLE_ALGORITHMS, 'Tuned MLFQ', 'Dynamic v5', 'Guard candidate']:
                print(item['workload_id'], policy, flush=True)
                row = {'workload_id': item['workload_id'], 'stratum': item['stratum'], 'policy': policy}
                started = time.monotonic(); signal.alarm(20)
                try:
                    router = None; guard = None
                    if policy in {'Dynamic v5', 'Guard candidate'}:
                        guard = NonPreemptiveAdmissionGuard(model) if policy == 'Guard candidate' else None
                        router = run_dynamic(jobs, guard or model, config); result = router.simulation
                    else:
                        fn, kwargs = (mlfq, {'quanta': (1, 2, 4), 'aging_threshold': 40}) if policy == 'Tuned MLFQ' else DEPLOYABLE_ALGORITHMS[policy]
                        result = run_simulation(policy, fn, jobs, **kwargs)
                    signal.alarm(0); results[policy] = result
                    row.update(status='COMPLETE', avg_waiting_ms=result.avg_waiting_time,
                        avg_response_ms=result.avg_response_time,
                        p95_response_ms=_percentile([p.response_time for p in result.process_metrics], .95),
                        starvation=aggregate_fairness(result.process_metrics)['starvation_count'],
                        accepted_switches=sum(d.accepted for d in router.decisions) if router else 0,
                        nonaccepted_reviews=sum(not d.accepted for d in router.decisions) if router else 0,
                        decision_examples=len(router.decisions) if router else 0,
                        decision_p99_ms=router.transition_p99_ms if router else None,
                        admission_vetoes=guard.veto_count if guard else None)
                    if router:
                        decisions.append({'workload_id': item['workload_id'], 'policy': policy,
                            'reasons': dict(Counter(d.reason for d in router.decisions)),
                            'guard_raw_actions': dict(Counter(guard.raw_actions)) if guard else None,
                            'accepted_events': [asdict(d) for d in router.decisions if d.accepted][:10]})
                    if policy == 'Guard candidate' and 'Tuned MLFQ' in results:
                        # Structural prediction from tree audit, verified rather than claimed.
                        assert result.process_metrics == results['Tuned MLFQ'].process_metrics
                        row['identical_process_metrics_to_tuned_mlfq'] = True
                except TimeoutError as error:
                    row.update(status='TIMEOUT', reason=str(error))
                finally:
                    signal.alarm(0)
                row['wall_seconds'] = time.monotonic() - started; batch.append(row)
            refs = {p: results[p] for p in DEPLOYABLE_ALGORITHMS if p in results}
            for row in batch:
                row['weighted_score'] = score_result_against_reference(results[row['policy']], refs) if row['policy'] in results and len(refs) == 5 else None
            rows.extend(batch)
            write(OUTPUT / 'audit_progress.json', {'rows': rows, 'decisions': decisions})
    finally:
        signal.signal(signal.SIGALRM, previous_signal)
    write(OUTPUT / 'audit.json', {'rows': rows, 'decisions': decisions, 'protocol': protocol})
    assert all(sha(path) == digest for path, digest in protected.items())
    write(OUTPUT / 'preservation.json', {'protected_files': len(protected), 'unchanged': True})


def summarize():
    audit = json.loads((OUTPUT / 'audit.json').read_text())
    old = json.loads((PREVIOUS / 'summary.json').read_text())
    selected = json.loads((PREVIOUS / 'selection_manifest.json').read_text())['selected']
    decisions = json.loads((PREVIOUS / 'baseline_decisions.json').read_text())['rows']
    original_rows = json.loads((PREVIOUS / 'baseline_rows.json').read_text())['rows']
    groups = {}
    for row in audit['rows']:
        groups.setdefault(row['workload_id'], {})[row['policy']] = row
    common = [wid for wid, values in groups.items() if len(values) == 8 and all(r['status'] == 'COMPLETE' for r in values.values())]
    fields = ['weighted_score', 'avg_waiting_ms', 'avg_response_ms', 'p95_response_ms',
              'starvation', 'accepted_switches', 'nonaccepted_reviews', 'decision_examples', 'decision_p99_ms']
    policies = list(dict.fromkeys(r['policy'] for r in audit['rows']))
    metrics = {p: {key: mean([groups[wid][p][key] for wid in common if groups[wid][p].get(key) is not None])
                         if any(groups[wid][p].get(key) is not None for wid in common) else None for key in fields} for p in policies}
    paired = {}
    for comparator in ['Tuned MLFQ', 'Dynamic v5', 'Round Robin']:
        paired[comparator] = {key: paired_bootstrap_ci([groups[wid]['Guard candidate'][key] - groups[wid][comparator][key] for wid in common])
                              for key in ['weighted_score', 'p95_response_ms', 'starvation']} if common else {}
    dynamic_complete = [r for r in audit['rows'] if r['policy'] == 'Guard candidate' and r['status'] == 'COMPLETE']
    gates = {
        'Weighted score improvement (CI upper < 0)': bool(common) and paired['Tuned MLFQ']['weighted_score']['ci_high'] < 0,
        'P95 response non-regression (CI upper ≤ 0)': bool(common) and paired['Tuned MLFQ']['p95_response_ms']['ci_high'] <= 0,
        'Mean starvation non-regression': bool(common) and paired['Tuned MLFQ']['starvation']['mean'] <= 0,
        'Maximum workload routing P99 < 10 ms': bool(dynamic_complete) and max(r['decision_p99_ms'] for r in dynamic_complete) < 10,
        'Original RR score gate': bool(common) and paired['Round Robin']['weighted_score']['ci_high'] <= 0,
        'Original RR P95 gate': bool(common) and paired['Round Robin']['p95_response_ms']['ci_high'] < 0,
        'All selected workloads complete': len(common) == len(audit['protocol']['selected']),
        'Untouched holdout improvement established': False,
    }
    historical_linux = json.loads(Path('results/real_desktop_ml/decision-tree-demo/summary.json').read_text())
    main_metrics = {p: item['common_complete_means'] for p, item in old['policy_summary'].items()}
    complete_v5 = [r for r in original_rows if r['policy'] == 'Dynamic v5' and r['status'] == 'COMPLETE']
    main_decisions = sum(d['decisions'] for d in decisions if d['complete'])
    main_accepted = sum(d['accepted_switches'] for d in decisions if d['complete'])
    rejection_reasons = Counter()
    for d in decisions:
        if d['complete']:
            rejection_reasons.update({reason: count for reason, count in d['reasons'].items()
                                     if reason in {'cost_margin', 'dwell_blocked', 'arrival_risk', 'first_service_protection'}})
    assert sum(rejection_reasons.values()) == main_decisions - main_accepted
    result = {
        'schema_version': 1, 'dataset': 'Microsoft Azure Functions 2019 revision 2 · cleaned schema 2',
        'source_url': 'https://github.com/Azure/AzurePublicDataset/blob/master/AzureFunctionsDataset2019.md',
        'attribution': 'CC-BY · Mohammad Shahrad et al., Serverless in the Wild, USENIX ATC 2020',
        'dataset_workloads': 510, 'dataset_processes': 520408, 'genuine_scheduler_events': False,
        'model': str(MODEL), 'model_sha256': sha(MODEL),
        'training': {'occurred': False, 'reason': 'No local cleaned Linux captures, fitted Linux model or compatible observed-state/finite-action cost rows. Azure saved static-policy costs are not v5 decision-cost targets; saved predicted vectors lack paired actual action costs.',
                     'splits': {name: {'workloads': 0, 'decision_examples': 0, 'mae': None, 'rmse': None, 'r_squared': None} for name in ['train', 'validation', 'test']}},
        'label_eligibility': {'azure': 'Inputs support proxy-only simulated static-policy costs. Compatible feasible-duration dynamic action-cost rows would require a separately designed development-label experiment; none are saved here.',
                              'linux': 'Complete cleaned switch/wakeup/exit captures can support observed metrics and development replay labels, subject to the frozen contract; source captures and labels are unavailable locally.',
                              'fixtures': 'tests/fixtures/real_traces/source_tiers.jsonl contains source-tier examples, not eligible real-capture research observations.'},
        'linux': {'local_cleaned_captures_available': False, 'compatible_fitted_model_available': False,
                  'source': 'results/real_desktop_ml/decision-tree-demo/summary.json',
                  'saved_summary_only': True, 'reported_processes': historical_linux['dataset']['process_count'],
                  'reported_events': historical_linux['dataset']['event_count'],
                  'trace_splits': historical_linux['trace_counts'], 'action_row_splits': historical_linux['row_counts'],
                  'status': historical_linux['gates']['status'],
                  'limitation': 'Saved pilot Linux replay summary concerns a different model; source captures/labels are unavailable locally for verification. Not a Dynamic ML v5 result or kernel scheduler validation.'},
        'external': {'source': str(PREVIOUS / 'summary.json'), 'report': str(PREVIOUS / 'REPORT.md'),
                     'selected_workloads': old['selected'], 'completed_workloads': old['all_policy_complete'],
                     'selected_processes': sum(w['processes'] for w in selected),
                     'completed_processes': sum(w['processes'] for w in selected if w['workload_id'] in old['common_workload_ids']),
                     'policy_attempts': len(original_rows), 'timeouts': len(old['timeouts']), 'failures': old['timeouts'],
                     'decision_examples': main_decisions, 'accepted_switches': main_accepted,
                     'nonaccepted_reviews': main_decisions - main_accepted,
                     'rejected_switch_reviews': sum(rejection_reasons.values()),
                     'rejection_reasons': dict(rejection_reasons),
                     'switch_count_scope': 'Completed v5 runs only. Rejected switching reviews derive from saved margin/dwell/arrival/first-service reason counts; no same-policy holds occur in this subset. Accepted transitions include mandatory MLFQ returns, not just learned departures.',
                     'max_workload_decision_p99_ms': max(r['decision_p99_ms'] for r in complete_v5),
                     'metrics': main_metrics, 'gates': old['gates'],
                     'paired_vs_tuned': old['paired_comparisons_dynamic_minus_static']['Tuned MLFQ'],
                     'improved_over_tuned_mlfq': False},
        'candidate': {'name': 'Non-preemptive admission guard v1', 'source': str(OUTPUT / 'audit.json'),
                      'selected_workloads': len(audit['protocol']['selected']), 'completed_workloads': len(common),
                      'processes': sum(w['processes'] for w in audit['protocol']['selected']),
                      'completed_processes': sum(w['processes'] for w in audit['protocol']['selected'] if w['workload_id'] in common),
                      'timeouts': [r for r in audit['rows'] if r['status'] != 'COMPLETE'],
                      'metrics': metrics, 'paired': paired, 'gates': gates,
                      'admission_vetoes': sum(r['admission_vetoes'] for r in dynamic_complete),
                      'maximum_workload_p99_ms': max(r['decision_p99_ms'] for r in dynamic_complete) if dynamic_complete else None,
                      'all_completed_schedules_match_tuned': all(r.get('identical_process_metrics_to_tuned_mlfq') for r in dynamic_complete),
                      'promoted': False, 'training': False,
                      'limitation': f"Fresh development audit only; {sum(w['processes'] for w in audit['protocol']['selected'] if w['workload_id'] in common)} processes in the common completed subset. Four low and two medium contention groups selected; no eligible fresh high-contention groups under fixed caps. Reserved holdout untouched. Veto is a controller safety rule, not a learned improvement."},
        'limitations': 'One tick = 1 ms. Daily wall-clock means are CPU-demand proxies; within-minute arrivals are reconstructed. I/O, actual CPU bursts and OS ready queues are unavailable. Means use identical all-policy-complete workloads; eight older timeouts are retained. Azure scores use five static reference bounds, separate from synthetic scores. No real-kernel or population-wide superiority claim.',
        'recommendation': 'Retain tuned static MLFQ (1,2,4), aging 40. V5 remains experimental. Guard candidate is not promoted.',
    }
    write(OUTPUT / 'dashboard.json', result)
    header = '# Real-source Dynamic ML review\n\nNo training or model promotion. Azure-derived simulator evidence, not measured kernel performance.\n\n'
    text = header + result['training']['reason'] + '\n\n' + result['linux']['limitation'] + '\n\n'
    text += '## Existing v5 external evaluation (preserved)\n\n'
    text += f"{old['all_policy_complete']}/{old['selected']} common completed workloads; {result['external']['completed_processes']} processes; {main_decisions} v5 decisions; {main_accepted} accepted transitions; {main_decisions-main_accepted} rejected-or-held reviews. {len(old['timeouts'])} policy timeouts retained.\n\n"
    text += '## Fresh safety audit\n\n' + audit['protocol']['scope'] + '. ' + audit['protocol']['missing_coverage'] + '\n\n'
    text += f"{len(common)}/{len(audit['protocol']['selected'])} common complete workloads; {result['candidate']['processes']} selected processes. Training/validation/test examples: 0/0/0. MAE, RMSE, R²: not recorded, not estimated.\n\n"
    text += '| Policy | Weighted score | Avg waiting ms | Avg response ms | Mean P95 ms | Accepted switches/workload | Routing P99 ms (mean workload P99) |\n|---|---:|---:|---:|---:|---:|---:|\n'
    for p in ['Dynamic v5', 'Tuned MLFQ', 'Guard candidate']:
        text += '| ' + p + ' | ' + ' | '.join('Not recorded' if metrics[p][k] is None else f'{metrics[p][k]:.6f}' for k in
            ['weighted_score', 'avg_waiting_ms', 'avg_response_ms', 'p95_response_ms', 'accepted_switches', 'decision_p99_ms']) + ' |\n'
    text += '\nThe guard vetoes non-preemptive FCFS/Priority proposals without changing the fitted tree, features, objective, safe boundaries or dwell. The tree never selects RR/Priority-RR, so the candidate collapses to continuous MLFQ; this is verified per process rather than presented as ML superiority.\n\n'
    text += '## Gates and paired uncertainty\n\n' + json.dumps({'gates': gates, 'paired': paired}, indent=2) + '\n\n'
    text += result['recommendation'] + '\n\n' + result['limitations'] + '\n\n'
    text += 'Exact frozen metadata-only selection, source groups, exclusions and parameters: `protocol.json`. All attempts and rejection reasons: `audit.json`. Dataset inventory, absent regression metrics and dashboard inputs: `dashboard.json`. Prior Azure holdout groups were neither evaluated nor used for selection. No historical artifacts or research status were modified.\n\nReproduce in a fresh versioned OUTPUT: `.venv/bin/python -m autoscheduler.real_source_review`; summarize saved outcomes only with `--summarize`.\n'
    (OUTPUT / 'REPORT.md').write_text(text)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--summarize', action='store_true')
    if parser.parse_args().summarize:
        summarize()
    else:
        run()
