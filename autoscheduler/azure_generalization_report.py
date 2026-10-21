"""Summarize saved Azure baseline results without rerunning simulations."""
from collections import Counter, defaultdict
import argparse
import csv
import json
from pathlib import Path
from statistics import mean

from autoscheduler.azure_generalization import OUTPUT, write
from autoscheduler.experiments import paired_bootstrap_ci

METRICS = ('weighted_score', 'avg_waiting_ms', 'avg_response_ms', 'p95_response_ms',
           'avg_turnaround_ms', 'throughput_jobs_per_ms', 'utilization_fraction',
           'starvation', 'context_switches', 'accepted_switches', 'decision_p99_ms')


def summarize():
    rows = json.loads((OUTPUT / 'baseline_rows.json').read_text())['rows']
    # These four wrappers expose no timing hook. Preserve raw records, but never
    # present the initial empty-list percentile placeholder as measured latency.
    uninstrumented = {'FCFS', 'Round Robin', 'Priority', 'Priority RR'}
    for row in rows:
        if row['policy'] in uninstrumented and row['status'] == 'COMPLETE':
            row['decision_p99_ms'] = None
            row['latency_scope'] = 'not instrumented'
    write(OUTPUT / 'measurement_notes.json', {
        'static_latency_unavailable': sorted(uninstrumented),
        'raw_record_correction': 'Initial baseline_rows.json uses zero for an empty timing list in these wrappers. Derived CSV/report/summary correctly show unavailable; raw records are retained. Harness now emits null.',
        'scheduling_metrics_affected': False})
    manifest = json.loads((OUTPUT / 'selection_manifest.json').read_text())
    previous = json.loads(Path('results/azure_external_pilot/selection.json').read_text())
    previously_seen = {manifest['all_source_groups'][w['workload_id']] for w in previous}
    reserved = set(manifest['holdout_groups'])
    clean_reserve = reserved - previously_seen
    holdout_audit = {'rule': 'Subtract every historical-pilot provenance group, including the timed-out selection, from the reserved set; no evaluation selection is changed.',
                     'historically_seen_reserved_groups': sorted(reserved & previously_seen),
                     'genuinely_untouched_groups': sorted(clean_reserve),
                     'genuinely_untouched_workload_ids': [wid for wid, group in manifest['all_source_groups'].items() if group in clean_reserve],
                     'evaluated': False}
    write(OUTPUT / 'untouched_holdout_manifest.json', holdout_audit)
    diagnostics = json.loads((OUTPUT / 'baseline_decisions.json').read_text())['rows']
    original = json.loads((OUTPUT / 'original_pilot_diagnosis.json').read_text())['rows']
    population = json.loads((OUTPUT / 'population_characteristics.json').read_text())['workloads']
    policies = list(dict.fromkeys(r['policy'] for r in rows))
    by_id = defaultdict(dict)
    for row in rows:
        by_id[row['workload_id']][row['policy']] = row
    common = [wid for wid, values in by_id.items()
              if len(values) == len(policies) and all(v['status'] == 'COMPLETE' for v in values.values())]

    def averages(subset):
        return {metric: mean([r[metric] for r in subset if r.get(metric) is not None])
                if any(r.get(metric) is not None for r in subset) else None for metric in METRICS}

    policy_summary = {p: {'completed': sum(r['status'] == 'COMPLETE' for r in rows if r['policy'] == p),
                          'timeouts': sum(r['status'] == 'TIMEOUT' for r in rows if r['policy'] == p),
                          'common_complete_means': averages([by_id[wid][p] for wid in common])}
                      for p in policies}
    comparisons = {}
    for p in policies[:-1]:
        result = {}
        for metric in METRICS:
            pairs = [(wid, values['Dynamic v5'][metric] - values[p][metric]) for wid, values in by_id.items()
                     if values['Dynamic v5']['status'] == values[p]['status'] == 'COMPLETE'
                     and values['Dynamic v5'].get(metric) is not None and values[p].get(metric) is not None]
            if pairs:
                result[metric] = {**paired_bootstrap_ci([value for _, value in pairs]), 'pairs': len(pairs),
                                  'workload_ids': [wid for wid, _ in pairs]}
        comparisons[p] = result
    static = policies[:-1]
    primary = min(static, key=lambda p: policy_summary[p]['common_complete_means']['weighted_score']) if common else None
    gates = {}
    if primary:
        paired = comparisons[primary]
        dynamic_rows = [r for r in rows if r['policy'] == 'Dynamic v5' and r['status'] == 'COMPLETE']
        gates = {'conditional_primary_score_ci_upper_lt_zero': paired['weighted_score']['ci_high'] < 0,
                 'conditional_primary_p95_ci_upper_le_zero': paired['p95_response_ms']['ci_high'] <= 0,
                 'conditional_primary_mean_starvation_le_zero': paired['starvation']['mean'] <= 0,
                 'completed_workload_max_routing_p99_strictly_lt_10ms': max(r['decision_p99_ms'] for r in dynamic_rows) < 10,
                 'conditional_rr_score_ci_upper_le_zero': comparisons['Round Robin']['weighted_score']['ci_high'] <= 0,
                 'conditional_rr_p95_ci_upper_lt_zero': comparisons['Round Robin']['p95_response_ms']['ci_high'] < 0,
                 'all_selected_workloads_complete': len(common) == len(manifest['selected']),
                 'independent_untouched_holdout_improvement_established': False,
                 'promoted': False}
    family = {}
    for name in dict.fromkeys(item['stratum'] for item in manifest['selected']):
        ids = [wid for wid in common if by_id[wid]['Dynamic v5']['stratum'] == name]
        family[name] = {'selected': sum(w['stratum'] == name for w in manifest['selected']),
                        'all_policy_complete': len(ids),
                        'common_complete_means': {p: averages([by_id[wid][p] for wid in ids]) for p in policies}}
    wins = {}
    for p in ('Tuned MLFQ', 'MLFQ'):
        wins[p] = {}
        for metric in ('weighted_score', 'p95_response_ms'):
            pairs = [(wid, values['Dynamic v5'][metric] - values[p][metric]) for wid, values in by_id.items()
                     if values['Dynamic v5']['status'] == values[p]['status'] == 'COMPLETE'
                     and values['Dynamic v5'].get(metric) is not None and values[p].get(metric) is not None]
            wins[p][metric] = {'better': [wid for wid, delta in pairs if delta < -1e-10],
                              'tied': [wid for wid, delta in pairs if abs(delta) <= 1e-10],
                              'worse': [wid for wid, delta in pairs if delta > 1e-10]}
    cohort = {}
    for name in sorted({w['cohort'] for w in population}):
        values = [w for w in population if w['cohort'] == name]
        cohort[name] = {'workloads': len(values), 'jobs': sum(w['processes'] for w in values),
                        'low_contention': sum(w['arrival_work_pending_fraction'] < .05 for w in values),
                        'medium_contention': sum(.05 <= w['arrival_work_pending_fraction'] < .5 for w in values),
                        'high_contention': sum(w['arrival_work_pending_fraction'] >= .5 for w in values)}
    reasons = Counter(); actions = Counter()
    for row in original:
        reasons.update(row['reasons']); actions.update(row['raw_actions'])
    summary = {'status': 'EXPLORATORY_AZURE_PROXY_DEVELOPMENT_BASELINE_NO_MODEL_PROMOTED',
               'selected': len(manifest['selected']), 'all_policy_complete': len(common), 'common_workload_ids': common,
               'timeouts': [r for r in rows if r['status'] != 'COMPLETE'], 'policy_summary': policy_summary,
               'primary_static_on_common_complete_subset': primary, 'paired_comparisons_dynamic_minus_static': comparisons,
               'bootstrap': {'samples': 10000, 'seed': 2027, 'confidence': .95,
                             'unit': 'one selected workload per connected function-provenance group',
                             'limitations': 'Exploratory, conditional on completed pairs and metadata-capped selection; not population or holdout evidence; no multiplicity adjustment.'},
               'gates': gates, 'families': family, 'dynamic_wins': wins, 'population_cohorts': cohort,
               'original_pilot': {'completed': len(original), 'decision_opportunities': sum(w['decision_opportunities'] for w in original),
                                  'model_invocations': sum(w['model_invocations'] for w in original),
                                  'accepted_switches': sum(w['accepted_switches'] for w in original),
                                  'reviews_with_competition': sum(w['reviews_with_competing_ready_jobs'] for w in original),
                                  'raw_actions': dict(actions), 'reasons': dict(reasons)},
               'new_model': None, 'holdout_evaluated': False, 'untouched_holdout_audit': holdout_audit}
    write(OUTPUT / 'summary.json', summary)
    columns = list(dict.fromkeys(k for r in rows for k in r))
    with (OUTPUT / 'workloads.csv').open('w') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns); writer.writeheader(); writer.writerows(rows)
    write_report(summary, manifest)
    return summary


def write_report(summary, manifest):
    lines = ['# Azure generalization: controlled development baseline', '',
             '**Azure-derived simulation only. No new model fitted or promoted. Holdout remains untouched.**', '',
             'Dataset: Microsoft Azure Functions 2019 revision 2, CC-BY; attribution to Mohammad Shahrad et al., '
             '“Serverless in the Wild,” USENIX ATC 2020. Existing cleaned schema-2 seed-42 input contains 510 workloads '
             'and 520,408 reconstructed jobs. Source archive/member provenance remains in `AzureWorkloads/reports/`; '
             'no source data was regenerated. Published daily wall-clock means are CPU-demand proxies, not measured CPU bursts. '
             'Within-minute arrivals are reconstructed under the documented uniform-arrival assumption, not observed OS arrivals.', '',
             '## What the original equality meant', '',
             'The original 14 completed workloads reproduced their saved mean waiting, response and turnaround exactly. '
             'The fitted v5 artifact passed its feature/configuration contract and was invoked 7,878 times. '
             'It made 221 accepted policy transitions, but only 92 reviews had at least two ready jobs. '
             'Every workload had aggregate unfinished work at fewer than 5% of arrivals. '
             'No raw prediction selected No Switch and no compatibility/confidence fallback occurred. '
             'Equality therefore does not demonstrate learned generalization: most departures were blocked or had no scheduling choice to improve.', '',
             'Inspection of the unchanged depth-3 cost tree explains the proposals: it splits on only **completed burst variance, ready count, '
             'and arrival quiet time**, despite accepting 19 observed inputs. None of its seven leaves chooses No Switch as the first minimum. '
             'Four near-zero-variance leaves favor Priority; one heterogeneous/recent-arrival leaf has all costs tied at zero '
             'and proposes FCFS by action ordering. The other two heterogeneous leaves predict Priority benefits below the .005 margin. '
             'Thus a raw Priority/FCFS proposal is not evidence of useful adaptation. Neutral-priority and many other range violations '
             'do not directly change tree routing because those inputs are unused. See `model_tree_audit.json`.', '',
             'The raw proposals were screened by first-service protection (4,004 reviews), observed arrival risk (998), '
             'and cost margin (2,655); 114 ordinary transitions and 107 expiry returns were accepted. '
             'These reasons are not independent causal effect estimates. Per-workload arrivals, burst dispersion, pending-work contention, '
             'simulated duration, review counts, raw proposals, disposition, and full active-policy intervals are in '
             '`original_pilot_diagnosis.json`.', '',
             '## Protocol and coverage', '',
             f"Selected **{summary['selected']} whole development workloads**, seed 20261020, one per connected owner/app/function group. "
             f"{len(manifest['holdout_groups'])} of {manifest['source_group_count']} provenance components remain reserved; "
             f"{len(summary['untouched_holdout_audit']['genuinely_untouched_groups'])} are genuinely untouched after excluding three historical-pilot groups. "
             'Selection uses metadata, pending-work thresholds and predeclared CPU-demand caps, never policy outcomes. '
             'The selected IDs differ from the original 15 pilot IDs. Two selected source components were seen in that pilot '
             '(peak and high-load mixed); their reuse is explicitly diagnostic, not independent validation. '
             'All related hours, days and mixed snapshots stay on one side of the reserve boundary. '
             'The initial reserve mistakenly included three historically examined components. '
             '`untouched_holdout_manifest.json` explicitly subtracts them without changing the frozen development selection. '
             'The remaining reserve has no historical-pilot or current-investigation policy outcomes. '
             'Only two independent function components underlie all 56 peak snapshots.', '',
             'One tick = 1 ms; input jobs, reconstructed arrivals and daily wall-clock-mean duration proxies are unchanged. '
             'Five fixed eligible static policies provide within-workload normalization, separate from historical synthetic six-policy scores. '
             'Weights remain waiting .30, response .25, turnaround .20, utilization .15, throughput .10. '
             'Parameters, source hashes, pools, cap exclusions and reserved IDs are in `selection_manifest.json`. '
             'RR uses quantum 2; Priority-RR uses quantum 2/aging 8/cost 1; default MLFQ uses (2,4,8)/aging 20/cost 0; '
             'tuned MLFQ and v5 use (1,2,4)/aging 40/cost 0. Policy-specific costs are retained, not silently equalized. '
             'There is no added generic adaptive reconfiguration charge; this limits any claimed benefit. '
             'The static Priority policy has no aging and all Azure priorities are neutral, so FCFS/Priority equivalence is expected.', '',
             'Inherited policy-specific overhead confounds a pure algorithm-only comparison involving Priority-RR; '
             'the principal v5/default/tuned-MLFQ comparisons all use zero charged context-switch cost. '
             'Fixed 2-ms quanta and 10/20-ms review/dwell periods are not rescaled for these much longer wall-clock proxies. '
             'That unit-consistent but distribution-mismatched choice is explicit, not a tuning parameter.', '',
             'Throughput is completed jobs divided by simulator makespan; utilization is a fraction over that same simulated window, '
             'not the complete Azure source hour. P95 is computed within each workload and averaged across workloads. '
             'Starvation retains the report-only waiting-time > 3 × proxy CPU-demand criterion. '
             'Source-disjoint function groups can still share calendar periods or applications; bootstrap intervals do not model that dependence.', '',
             f"Each policy has a fixed 20-second wall-time budget. **{summary['all_policy_complete']}/{summary['selected']} workloads completed all seven policies**. "
             'All failures remain in `workloads.csv`; none are replaced. A weighted score is unavailable if any fixed reference times out. '
             'The following averages use the common all-policy-complete subset and cannot summarize the difficult censored workloads.', '',
             '| Policy | Complete/selected | Score | Wait ms | Response ms | P95 ms | Turnaround ms | Jobs/ms | Utilization | Starvation/workload | Switches/workload | Mean workload P99 ms |',
             '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for policy, item in summary['policy_summary'].items():
        m = item['common_complete_means']
        def fmt(key): return f'{m[key]:.6f}' if m[key] is not None else 'Unavailable'
        lines.append(f"| {policy} | {item['completed']}/{summary['selected']} | " + ' | '.join(fmt(k) for k in
            ('weighted_score','avg_waiting_ms','avg_response_ms','p95_response_ms','avg_turnaround_ms','throughput_jobs_per_ms',
             'utilization_fraction','starvation','accepted_switches','decision_p99_ms')) + ' |')
    lines += ['', 'Only MLFQ exposes a static ready-selection timing hook; other static latencies are unavailable, not zero (see `measurement_notes.json`). '
              'Dynamic latency includes feature extraction, model, safeguards and queue rebuild. '
              'Dynamic prediction observers add diagnostic overhead. These are simulator/controller timings, not Linux scheduling performance.', '',
              '## Paired comparisons and gates', '',
              f"Strongest static score on the common completed development subset: **{summary['primary_static_on_common_complete_subset']}**. "
              'This conditional comparator is not a holdout-selected deployment recommendation. '
              'Differences below are v5 minus comparator; lower is better. Intervals use 10,000 paired workload resamples, seed 2027, '
              'one workload per provenance component. Small, capped, censored development samples support only exploratory uncertainty.', '',
              '| Comparator | Metric | Pairs | Mean difference | 95% CI |', '|---|---|---:|---:|---|']
    for policy, result in summary['paired_comparisons_dynamic_minus_static'].items():
        for metric in ('weighted_score','p95_response_ms','starvation'):
            if metric in result:
                r = result[metric]
                lines.append(f"| {policy} | {metric} | {r['pairs']} | {r['mean']:.6f} | [{r['ci_low']:.6f}, {r['ci_high']:.6f}] |")
    lines += ['', 'Frozen gate thresholds are unchanged; conditional results do not compensate for missing coverage or untouched-holdout evidence.', '']
    lines += [f"- {key}: **{'pass' if value else 'fail / not established'}**" for key, value in summary['gates'].items()]
    lines += ['', '## Workload-family results', '', '| Stratum | Selected | All-policy complete | v5 score / P95 ms | Tuned MLFQ score / P95 ms |',
              '|---|---:|---:|---|---|']
    for name, item in summary['families'].items():
        def cell(p):
            m = item['common_complete_means'][p]
            return f"{m['weighted_score']:.6f} / {m['p95_response_ms']:.3f}" if m['weighted_score'] is not None else 'Unavailable'
        lines.append(f"| {name} | {item['selected']} | {item['all_policy_complete']} | {cell('Dynamic v5')} | {cell('Tuned MLFQ')} |")
    lines += ['', 'Exact workload-level better/tied/worse IDs and every reported metric are in `summary.json` and `workloads.csv`. '
              'Family results are descriptive; single-workload strata do not support credible family confidence intervals.', '',
              'On the 12 common completed workloads, v5 has a lower weighted score on three workloads '
              '(`azure-d13-0255`, `azure-d07-0132`, `azure-d10-0191`), ties four and worsens five versus tuned MLFQ. '
              'P95 improves on none, ties six and worsens six. Thus the three weighted-score wins are not safety-qualified wins. '
              'Mean workload P95 is 2197.908333 ms versus 2.912500 ms; score is 0.132043 versus 0.076082. '
              'Mean accepted transitions rise to 494.333 per workload. These values describe the completed subset only.', '',
              '## Representative confirmed response mechanism', '',
              '`representative_trace.json` retains a diagnostic replay of `azure-d07-0132` (25 jobs), including every review, '
              'each process arrival/first dispatch, and timeline prefixes under both policies. At 2,715,262 ms, the controller '
              'accepts Priority with one ready job, no unserved jobs, 27 ms of observed service and 27 ms since arrival. '
              'There is no completed burst history. Apart from the unused neutral-priority feature, this departure state is inside '
              'the training min/max ranges. Thirteen jobs then arrive while Priority completes the current non-preemptive burst. '
              'The first legal MLFQ return is 2,731,966 ms: **16,704 ms after departure**, with 13 unserved jobs and oldest '
              'first-service wait 15,279 ms. A representative arrival at 2,716,687 ms waits until 2,731,966 ms for first service; '
              'tuned MLFQ dispatches it at arrival. Workload P95 is 15,498.2 ms under v5 versus zero under tuned MLFQ.', '',
              'This is a dispatch-boundary limitation, not missing inference or a failed return rule: the nominal 20-ms target '
              'horizon is not a preemption timer for Priority/FCFS. The guard sees no pressure at departure and cannot inspect '
              'future arrivals or true remaining burst. The synthetic diagnostic regression test preserves this exact limitation '
              'on a tiny two-job example. Longer observed-history admission rules could be researched, but would not protect this '
              'first-burst departure without stronger evidence or more conservative action eligibility. Simply normalizing unused '
              'features or removing guards does not address the confirmed mechanism.', '',
              '## Supported mechanisms and justified changes', '',
              '- **Low contention:** confirmed for the original pilot; output equality persisted despite real inference and transitions. '
              'High hourly invocation count alone was an inadequate selection descriptor.',
              '- **Distribution mismatch:** v5 trained on counts 3/6/12/24/48, priorities 1–5, short synthetic bursts and I/O. '
              'Azure has neutral priority 0, up to 2,000 ready jobs, much longer duration proxies and no observed I/O. '
              '`training_feature_bounds.json` uses training groups only; `baseline_decisions.json` records per-feature range violations '
              'for complete and partial runs. Range violations are diagnostics, not calibrated uncertainty or inference inputs.',
              '- **Guards versus learned intent:** raw predictions, cost vectors, accepted events, competing-ready reviews and rejection counts '
              'are saved separately. The original equality was neither absent inference nor a learned No Switch action. '
              'Removing first-service or arrival safeguards would not be justified by this evidence.',
              '- **Runtime bottleneck:** bounded pre-change cProfile on the formerly timed-out peak identifies repeated ready-list minimum scans, '
              'sorting all MLFQ entries before aging eligibility, neutral-priority arithmetic, and dynamic exact-statistic feature extraction. '
              'Only two exact shortcuts were implemented: filter aging eligibility before sorting; return effective priority 1 immediately '
              'when already saturated. Dispatch ordering, aging timestamps, costs, features and model decisions are unchanged. '
              'Preserved-source equivalence tests compare complete timelines including I/O, arrivals, aging, nonzero overhead and routing safety. '
              'The remaining linear scans and feature costs still limit large queues; no unverified heap or feature rewrite was attempted.',
              '- **Bounded profiling after the shortcuts:** in equal 8-second partial cProfile windows, Priority-RR ready selections '
              'increase from 11,882 to 26,884, default MLFQ from 15,136 to 23,432, and dynamic dispatches from 6,525 to 8,000. '
              'MLFQ aging cumulative time falls from 3.474 to .957 seconds; dynamic aging from 1.548 to .345 seconds. '
              'This is single-run instrumented progress, not a repeated end-to-end speedup estimate; every profiled run remains incomplete. '
              'Both original and post-change partial profiles are retained. The shortcuts do not solve large-queue replay.',
              '- **Other hypotheses:** no evidence of compatibility fallback; generic switching cost is absent rather than a measured cause. '
              'Dwell, late non-preemptive reviews and admission guards constrain possible adaptation, but no controlled ablation establishes '
              'that relaxing them would safely improve Azure tails. Static comparisons show available alternatives; they are not finite-horizon '
              'counterfactual switch labels. No causal contribution is assigned without such evidence.', '',
              '## Decision', '',
              '**Do not promote Dynamic ML. Retain v5 as the experimental research candidate and tuned MLFQ as the existing simulator recommendation.** '
              'No new model or hyperparameter was selected: this development investigation does not establish a generalizable, safety-preserving '
              'model correction, and heavy-workload censoring prevents a representative overall ranking. The reserved Azure evaluation groups '
              'were deliberately not consumed. No before/after model improvement is claimed; runtime equivalence is the only implemented correction. '
              'Default MLFQ remains an important comparator, not a reason to change the frozen research configuration.', '',
              'Further model work would first require efficient semantically equivalent large-queue replay, then development-only feasible-action '
              'labels grouped by provenance and a frozen untouched evaluation. Real I/O and OS contention cannot be recovered from these proxies. '
              'The smallest controller research question is whether non-preemptive departures should require a validated observed-history '
              'burst-risk bound. Merely restricting this fitted tree to preemptive actions would collapse it to MLFQ, because none of its '
              'leaves selects RR/Priority-RR; it cannot establish a strict improvement. This requires new development evidence, not a guard removal. '
              'Do not fit missing I/O or true remaining CPU as features. Azure-derived simulation cannot establish real-kernel superiority.', '',
              '## Reproduction and preservation', '',
              'Use a fresh output path for any deliberate rerun; completed diagnosis/baseline files refuse overwrite. Commands: '
              '`.venv/bin/python -m autoscheduler.azure_generalization diagnose`, '
              '`.venv/bin/python -m autoscheduler.azure_generalization profile`, '
              '`.venv/bin/python -m autoscheduler.azure_generalization_evaluation`, '
              '`.venv/bin/python -m autoscheduler.azure_generalization_report`. '
              'Supply `--output results/<fresh-directory>` consistently to rerun without overwriting this experiment. '
              'The first three consume development simulation time; the final command reads saved results only. '
              'All source datasets, model artifacts, historical reports, dashboard and frozen protocols are preserved. '
              'Verification and preservation hashes are recorded in `verification.json`. No frontend changes, training, push or merge.']
    (OUTPUT / 'REPORT.md').write_text('\n'.join(lines) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    OUTPUT = parser.parse_args().output
    summarize()
