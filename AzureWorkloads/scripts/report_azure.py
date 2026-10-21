"""Describe refined selection and rounding; never clean data or run a model."""
import argparse
from collections import Counter
import csv
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from common import ROOT, dump, summary


def suite_statistics(payload):
    sizes=[];rates=[];bursts=[];fractions=[];unique=set();contexts={}
    for w in payload['workloads']:
        n=len(w['processes']);sizes.append(n)
        rates.append(n/(w.get('exposure_ms',3600000)/1000))
        bursts.extend(p['burst_time'] for p in w['processes'])
        fractions.append(w.get('sampling_fraction',1))
        for s in w['sources']:
            contexts[(s['day'],s['source_row'],s['start_minute'])]=sum(s['counts'])
        # Source invocation identity is encoded in PIDs; group prefixes are removed.
        for p in w['processes']:
            source_identity=p['pid'].split(':',1)[1]
            unique.add((w['day'],source_identity))
    return dict(workloads=len(sizes),jobs=sum(sizes),sizes=summary(sizes),
        realized_arrival_rate_per_second=summary(rates),burst_proxy_ms=summary(bursts),
        sampling_fraction=summary(fractions),unique_reconstructed_invocations=len(unique),
        selected_source_hour_contexts=len(contexts),source_hour_context_invocations=sum(contexts.values()))


def rounding_statistics(averages):
    values=np.asarray(averages,dtype=float)
    positive=values[np.isfinite(values)&(values>0)]
    error=np.ceil(positive)-positive
    result=dict(tick_ms=1,positive_published_means=len(positive),zero_published_means=int((values==0).sum()),
        fractional_positive_means=int((positive!=np.floor(positive)).sum()),
        absolute_error_ms=summary(error),relative_error_percent=summary(100*error/positive),short_duration_bins=[])
    for lower,upper,label in [(0,1,'0 < mean <= 1 ms'),(1,4,'1 < mean <= 4 ms'),(4,10,'4 < mean <= 10 ms')]:
        x=positive[(positive>lower)&(positive<=upper)]
        result['short_duration_bins'].append(dict(label=label,rows=len(x),
            absolute_error_ms=summary(np.ceil(x)-x),relative_error_percent=summary(100*(np.ceil(x)-x)/x)))
    result['hypothetical_fractional_examples']=[dict(mean_ms=x,burst_ticks=math.ceil(x),
        relative_error_percent=100*(math.ceil(x)-x)/x) for x in [.1,.5,1.2,2.25]]
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=ROOT)
    args=parser.parse_args();root=args.root
    read=lambda name:json.loads((root/name).read_text())
    before=read('reports/baseline/evaluation_workloads.json')
    after=read('cleaned/evaluation_workloads.json')
    cleaning=read('reports/cleaning_summary.json');selection=read('reports/selection_summary.json')
    validation=read('reports/validation_results.json')
    old_selection=read('reports/baseline/selection_summary.json')
    durations=pd.read_csv(root/'cleaned/azure_durations_cleaned.csv')
    invfiles=[f for f in cleaning['files'] if f['kind']=='invocation']
    total_calls=sum(f['observed_invocations'] for f in invfiles)
    over_cap_calls=sum(d['over_cap_invocations'] for d in old_selection['days'])
    over_cap_windows=sum(d['over_cap_windows'] for d in old_selection['days'])
    positive_windows=sum(d['positive_hour_windows'] for d in selection['high_load_days'])
    b=suite_statistics(before);a=suite_statistics(after)
    cohorts={cohort:suite_statistics(dict(workloads=[w for w in after['workloads'] if w['cohort']==cohort]))
             for cohort in sorted({w['cohort'] for w in after['workloads']})}
    rounding=rounding_statistics(durations.Average)
    jobs=pd.read_csv(root/'cleaned/azure_scheduler_jobs.csv',usecols=['Average','burst_time'])
    job_error=jobs.burst_time-jobs.Average
    rounding['selected_job_absolute_error_ms']=summary(job_error)
    rounding['selected_job_relative_error_percent']=summary(100*job_error/jobs.Average)
    source_cells=[]
    for w in after['workloads']:
        if 'hour_sample' in w['cohort']:
            for s in w['sources']:
                source_cells.extend(f for f in s['within_minute_inclusion_fractions'] if f is not None)
    snapshots=[w for w in after['workloads'] if w['cohort']=='local_rate_snapshot']
    rate_error=[100*(w['realized_arrival_rate_per_second']/w['reference_arrival_rate_per_second']-1) for w in snapshots]
    shape=[w['minute_shape_total_variation'] for w in after['workloads'] if 'hour_sample' in w['cohort']]
    coverage=dict(total_recorded_invocations=total_calls,old_cap_ineligible_hours=over_cap_windows,
        old_cap_ineligible_positive_hour_percent=100*over_cap_windows/positive_windows,
        old_cap_ineligible_invocations=over_cap_calls,old_cap_ineligible_invocation_percent=100*over_cap_calls/total_calls,
        after_cap_only_ineligible_invocations=0,
        before_unique_sampled_invocation_percent=100*b['unique_reconstructed_invocations']/total_calls,
        after_unique_sampled_invocation_percent=100*a['unique_reconstructed_invocations']/total_calls,
        before_unsampled_invocation_percent=100*(1-b['unique_reconstructed_invocations']/total_calls),
        after_unsampled_invocation_percent=100*(1-a['unique_reconstructed_invocations']/total_calls),
        before_selected_context_invocation_percent=100*b['source_hour_context_invocations']/total_calls,
        after_selected_context_invocation_percent=100*a['source_hour_context_invocations']/total_calls,
        note='Cap eligibility, selected source-hour context volume, and actual sampled occurrences are distinct. No claim of 100% traffic coverage.')
    comparison=dict(before=b,after=a,cohorts=cohorts,coverage=coverage,
        stratified_minute_shape_total_variation=summary(shape),within_minute_sampling_fraction=summary(source_cells),
        snapshot_rate_error_percent=summary(rate_error),rounding=rounding)
    dump(root/'reports/before_after_comparison.json',comparison)
    dump(root/'reports/rounding_analysis.json',rounding)
    dump(root/'reports/descriptive_statistics.json',dict(**comparison,
        observed_daily_function_mean_ms=summary(durations.Average),job_burst_proxy_ms=summary(jobs.burst_time)))
    match_counts=Counter()
    for f in invfiles:match_counts.update(f['match_counts'])
    quality=['# Refined Azure evaluation data quality','',
        'This run changes selection and derived artifacts only. No extraction, cleaning, scheduler modifications, training or model evaluation was performed. SHA-256 checks prove both original cleaned observation tables unchanged. Original cleaning/inspection/audit files remain historical inputs.', '',
        '| Existing cleaned table | Original rows | Retained rows | Missing numeric cells | Previously invalid cells blanked | Conflicting-key rows retained |',
        '|---|---:|---:|---:|---:|---:|']
    for kind,t in cleaning['totals'].items():
        quality.append(f'| {kind} | {t["original_rows"]:,} | {t["retained_rows"]:,} | {t["missing_cells"]:,} | {t["invalid_cells"]:,} | {t["conflicting_key_rows"]:,} |')
    quality+=['','No genuine duplicate rows or missing-identifier rows were dropped in the original cleaning. This refinement drops no observation records. Original audit: 24 invalid numeric cells across seven duration rows; two missing duration bounds remain missing.', '',
        '| Existing match eligibility | Invocation rows |','|---|---:|']
    quality += [f'| {key} | {value:,} |' for key,value in sorted(match_counts.items())]
    quality+=['',f'Executed validation passed: **{validation["passed"]}**. Constructed {validation["scheduler_jobs"]:,} valid Process objects in {validation["workloads"]} groups. Preserved every original control Process record. Checks include source rows and duration identifiers, original vs sampled minute counts, bounded quotas, distinct sampled ordinals, seeded reconstruction, snapshot exposure, integer milliseconds, positive bursts, neutral priority, absent I/O, and immutable cleaned-table hashes.', '',
        'Sampling is not cleaning: omitted invocations remain in the original cleaned files. High-volume sampled groups retain their entire original 60-bin source count vectors plus sampled counts and within-minute inclusion fractions. No missing/zero-duration value is fabricated or mapped to a positive CPU time.', '',
        '## Source interpretation', '',
        '[Official Microsoft dataset documentation](https://github.com/Azure/AzurePublicDataset/blob/master/AzureFunctionsDataset2019.md) describes wall-clock execution statistics in milliseconds, excluding cold starts. Invocation bins are recorded after execution; percentile columns summarize interval averages, not individual invocation latencies. Released daily means may have lost submillisecond precision, which cannot be recovered here.', '',
        'The data is CC-BY; retain attribution to Shahrad et al., “Serverless in the Wild,” USENIX ATC 2020. See README and the original extraction manifest for source provenance.', '',
        '## Limitations', '',
        'High-hour samples preserve the observed minute shape and quiet bins but attenuate absolute arrival rates. Local snapshots approximate original peak-minute rates only under uniform independent within-minute arrivals; they do not measure subminute bursts. All times are integer milliseconds. Long execution durations remain wall-clock proxies, not CPU demand. No I/O phases, priorities or dependencies are observed. Purposeful selection is not a population probability sample.']
    (root/'reports/data_quality_report.md').write_text('\n'.join(quality)+'\n')
    stats=['# Refined workload statistics and comparison','',
        '## Why the original cap excluded most invocation volume','',
        f'The old selector filtered entire function-hours before sampling. Its 2,000-job limit is only {2000/3600:.6g} arrivals/second averaged over an hour. Just {over_cap_windows:,} hours ({coverage["old_cap_ineligible_positive_hour_percent"]:.3f}% of positive usable hours) contain {over_cap_calls:,} invocations ({coverage["old_cap_ineligible_invocation_percent"]:.2f}% of all recorded invocations). The volume distribution is highly concentrated; a small share of busy hours dominates invocation counts. Eligibility filtering therefore removed that tail rather than sampling it.', '',
        '## Before versus after','',
        '| Measure | Original | Refined |','|---|---:|---:|',
        f'| Workloads | {b["workloads"]} | {a["workloads"]} |',
        f'| Jobs (including source overlaps across groups) | {b["jobs"]:,} | {a["jobs"]:,} |']
    for label,key in [('Processes/group','sizes'),('Realized arrivals/second','realized_arrival_rate_per_second'),('Burst proxy (ms)','burst_proxy_ms')]:
        stats.append(f'| {label}: median / P95 / max | '+ ' / '.join(f'{b[key][q]:.6g}' for q in ['p50','p95','max'])+' | '+' / '.join(f'{a[key][q]:.6g}' for q in ['p50','p95','max'])+' |')
    stats += [f'| Unique reconstructed source occurrences | {b["unique_reconstructed_invocations"]:,} | {a["unique_reconstructed_invocations"]:,} |',
        f'| Selected source-hour context volume / all calls | {coverage["before_selected_context_invocation_percent"]:.6f}% | {coverage["after_selected_context_invocation_percent"]:.6f}% |',
        f'| Actual unique sampled occurrences / all calls | {coverage["before_unique_sampled_invocation_percent"]:.6f}% | {coverage["after_unique_sampled_invocation_percent"]:.6f}% |',
        f'| All recorded invocations omitted from the small suite | {coverage["before_unsampled_invocation_percent"]:.6f}% | {coverage["after_unsampled_invocation_percent"]:.6f}% |',
        f'| Invocation volume ineligible solely due to cap | {coverage["old_cap_ineligible_invocation_percent"]:.2f}% | 0% |','',
        '**The last row is an eligibility change, not 100% traffic coverage.** Only a small, bounded subset is materialized. Context volume counts unique selected source-hours including their unsampled invocations; it is not the number of jobs reproduced. Source occurrences can overlap between groups; counts are deduplicated using day/source-row/minute/ordinal. Invocation ordinals are reconstructed identities, not observed timestamps.', '',
        '| Cohort | Groups | Jobs | Median jobs/group | Median realized rate/s | Median proxy ms |',
        '|---|---:|---:|---:|---:|---:|']
    for name,c in cohorts.items():
        stats.append(f'| {name} | {c["workloads"]} | {c["jobs"]:,} | {c["sizes"]["p50"]:.6g} | {c["realized_arrival_rate_per_second"]["p50"]:.6g} | {c["burst_proxy_ms"]["p50"]:.6g} |')
    stats += ['', '## Sampling design and distortion','',
        'All 286 original controls are retained with identical Process values, preserving low/medium arrivals, bursty and quiet hours, mixed functions, short/long durations and temporal variation. For each available day and six-hour block, additions target one seeded middle over-cap volume window and the maximum-volume window, rotating observed mean-duration strata. Each block also adds a same-hour mixture of short/middle/long duration functions and a local snapshot from the extreme hour. Selection is purposeful coverage; no population inclusion probability or global inverse weighting is claimed.', '',
        'Hourly samples apportion at most 2,000 jobs across function/minute cells. Proportional integer quotas use seeded tie breaking and a one-job lower bound for every originally active cell when feasible (at most 180 cells here). Individual invocation ordinals are then sampled uniformly without replacement within each cell. Original zero cells stay zero. All active cells remain active; low-count cells are overrepresented by the lower bound. Each cell stores its exact selected/original fraction; the overall group fraction is selected jobs/original source-hour count. Conditional cell inclusion weights do not correct the purposeful choice of hours/functions.', '',
        f'For sampled hours, normalized minute-shape total variation: median {comparison["stratified_minute_shape_total_variation"]["p50"]:.6g}, P95 {comparison["stratified_minute_shape_total_variation"]["p95"]:.6g}, maximum {comparison["stratified_minute_shape_total_variation"]["max"]:.6g}. This is half the L1 distance between original and sampled minute proportions; 0 means identical shape. Raw Fano factors shrink with thinning and must not be read as preserved absolute burstiness.', '',
        'Local snapshots select the busiest minute of an extreme source hour. Given N observed invocations, a seeded random block of K consecutive reconstructed invocation ranks is sampled. Joint uniform order statistics are generated using Dirichlet gaps in O(K) memory; the full N arrivals are never expanded. Times are floored to integer milliseconds. If K=N the entire minute is retained; otherwise the exposure runs from the first selected timestamp to one millisecond after the last. Snapshot per-minute inclusion fraction and exposure fraction are recorded separately from the fraction of the entire source hour represented. Boundary ties can omit other conceptual arrivals with the same rounded millisecond. Arrival origins differ by cohort and are explicit.', '',
        f'Snapshot realized-vs-original peak-minute rate error: median {summary(rate_error)["p50"]:.6g}%, P95 {summary(rate_error)["p95"]:.6g}%, minimum {summary(rate_error)["min"]:.6g}%, maximum {summary(rate_error)["max"]:.6g}%. Finite order-statistic variation, conditioning on K ranks, and millisecond boundary rounding explain departures. This is not a measurement of within-minute arrival behavior.', '',
        '## Duration units and rounding','',
        'Both arrivals and bursts use **1 tick = 1 ms**. Burst = ceil(positive published daily Average in ms). No time compression or change to the previous burst mapping is introduced. These are wall-clock proxies, never true CPU burst measurements.', '',
        f'Of {rounding["positive_published_means"]:,} positive published daily means, {rounding["fractional_positive_means"]:,} are fractional. Maximum pipeline rounding error is {rounding["absolute_error_ms"]["max"]:.6g} ms ({rounding["relative_error_percent"]["max"]:.6g}%); selected jobs have maximum error {rounding["selected_job_absolute_error_ms"]["max"]:.6g} ms.', '',
        '| Published daily mean | Function/day rows | Maximum added rounding error (ms) | Maximum relative error |','|---|---:|---:|---:|']
    for bin in rounding['short_duration_bins']:
        stats.append(f'| {bin["label"]} | {bin["rows"]:,} | {bin["absolute_error_ms"].get("max",0):.6g} | {bin["relative_error_percent"].get("max",0):.6g}% |')
    stats += ['',f'There are {rounding["zero_published_means"]:,} published zero means in retained duration observations. They remain unchanged and are ineligible for positive Process bursts; no 1-ms floor is invented for them. Integer published averages do not imply integer individual invocation durations or zero upstream quantization error. The unrounded means and original rounding convention are unavailable, so true submillisecond distortion cannot be quantified or recovered.', '',
        'For hypothetical positive fractional means (not generated jobs), ceiling 0.1 ms to 1 ms adds 900%; 0.5→1 ms adds 100%; 1.2→2 ms adds 66.7%; 2.25→3 ms adds 33.3%. Relative ceiling error is unbounded as a true positive mean approaches zero. Daily averaging and using wall-clock time as CPU demand are much larger unresolved modeling assumptions than the measured conversion error in these published integer means.', '',
        '## Controlled external evaluation assessment','',
        '**Suitable as a controlled, bounded external-trace-derived workload suite**, provided cohorts are reported separately and conclusions explicitly condition on reconstruction assumptions. It now contains sources from the high-volume tail, unchanged low/medium/quiet controls, mixed functions, 14 source days and all four six-hour blocks. Hour samples support comparisons at fixed observed temporal shape and reduced rate; snapshots support local-rate stress tests under the uniform-arrival assumption.', '',
        '**Insufficient for population-level or production Azure scheduling claims.** Sampling fractions differ greatly; selected hours and functions are not a probability sample. Do not pool raw jobs or workloads as if they estimated invocation-weighted Azure performance. There are no measured CPU/I/O bursts, multicore state, dependencies, true individual latencies, actual subminute starts or cold-start timings. Full-traffic concurrency and true serverless execution are not reproduced. Overlapping source function/day/hour observations must be grouped to prevent leakage in any later split.', '',
        'The prior synthetic comparison remains in reports/baseline/descriptive_statistics.json. Synthetic profiles use 8–12 jobs, uncalibrated ticks, repeated CPU/I/O phases and priorities 1–5. Refined Azure groups use explicit milliseconds, up to 2,000 jobs, one proxy burst, no I/O and priority 0. Existing short-job thresholds, quantums and model feature ranges therefore need a separately specified calibration phase. No scheduler or model was trained or evaluated here.']
    (root/'reports/workload_statistics.md').write_text('\n'.join(stats)+'\n')
    pd.DataFrame([dict(workload_id=w['workload_id'],cohort=w['cohort'],day=w['day'],start_minute=w['start_minute'],
        processes=w['job_count'],original_invocations=w['observed_count'],sampling_fraction=w['sampling_fraction'],
        exposure_ms=w['exposure_ms'],reference_rate_per_second=w['reference_arrival_rate_per_second'],
        realized_rate_per_second=w['realized_arrival_rate_per_second'],functions=len(w['sources']),
        original_quiet_fraction=w['quiet_fraction'],sampled_quiet_fraction=w['sampled_quiet_fraction'],
        minute_shape_total_variation=w['minute_shape_total_variation'],reasons=';'.join(w['reasons']))
        for w in after['workloads']]).to_csv(root/'reports/workload_manifest.csv',index=False)
    plots=root/'reports/plots';plots.mkdir(exist_ok=True)
    def save(name):
        plt.tight_layout();plt.savefig(plots/name,dpi=150);plt.close()
    h=old_selection['minute_count_histogram'];used=[i for i,n in enumerate(h['counts']) if n]
    labels=[str(int(h['edges'][i]))+'–'+str(int(h['edges'][i+1])-1) for i in used]
    plt.figure(figsize=(11,4));plt.bar(labels,[h['counts'][i] for i in used]);plt.yscale('log');plt.xticks(rotation=55,ha='right')
    plt.xlabel('Observed invocations / function-minute');plt.ylabel('Original intervals (log)');save('arrival_rate_distribution.png')
    x=durations.loc[durations.Average>0,'Average'];plt.figure(figsize=(8,4));plt.hist(x,bins=np.geomspace(x.min(),x.max()+1,60));plt.xscale('log');plt.yscale('log');plt.xlabel('Published daily wall-clock mean (ms)');plt.ylabel('Function/day rows');save('execution_duration_distribution.png')
    plt.figure(figsize=(8,4));plt.hist([len(w['processes']) for w in after['workloads']],bins=30);plt.xlabel('Processes / refined group');plt.ylabel('Groups');save('workload_size_distribution.png')
    plt.figure(figsize=(9,4));plt.hist(np.log10([w['sampled_fano']+1 for w in after['workloads'] if w['cohort']!='local_rate_snapshot']),bins=35);plt.xlabel('log10(1 + sampled minute-count Fano), hourly cohorts only');plt.ylabel('Groups');save('burstiness.png')
    plt.figure(figsize=(8,4));plt.bar([f['day'] for f in invfiles],[f['observed_invocations'] for f in invfiles]);plt.xlabel('Source day');plt.ylabel('Original recorded invocations');save('daily_variation.png')
    plt.figure(figsize=(10,4))
    for f in invfiles:plt.plot(np.arange(1440)/60,f['minute_totals'],alpha=.6,label=str(f['day']))
    plt.xlabel('Hour within original source day');plt.ylabel('Original invocations / minute');plt.legend(ncol=7,title='Day',fontsize=7);save('temporal_variation.png')
    sample=max((w for w in after['workloads'] if w['cohort']=='high_load_hour_sample'),key=lambda w:w['observed_count'])
    plt.figure(figsize=(10,4));plt.plot(np.array(sample['observed_minute_counts'])/sample['observed_count'],label='Original minute proportions');plt.plot(np.array(sample['sampled_minute_counts'])/sample['job_count'],label='Sampled minute proportions',linestyle='--');plt.xlabel('Minute in source hour');plt.ylabel('Fraction of invocations');plt.legend();save('selected_bursty_windows.png')
    fig,axes=plt.subplots(2,2,figsize=(11,8))
    for label,payload in [('Original',before),('Refined',after)]:
        ws=payload['workloads']
        vectors=[[len(w['processes']) for w in ws],[len(w['processes'])/(w.get('exposure_ms',3600000)/1000) for w in ws],
                 [p['burst_time'] for w in ws for p in w['processes']],[np.mean(np.asarray(w.get('sampled_minute_counts',w['observed_minute_counts']))==0) for w in ws if w.get('cohort')!='local_rate_snapshot']]
        for ax,values,title,log in zip(axes.flat,vectors,['Processes/group','Realized arrivals/second','Wall-clock burst proxy (ms)','Quiet fraction (hour groups)'],[False,True,True,False]):
            transformed=np.log10(values) if log else values
            ax.hist(transformed,bins=35,alpha=.5,label=label,density=True);ax.set_xlabel(('log10 ' if log else '')+title);ax.set_ylabel('Density')
    axes[0,0].legend();save('before_after_distributions.png')
    plt.figure(figsize=(9,4));plt.hist(np.log10([w['sampling_fraction'] for w in after['workloads'] if w['cohort']!='retained_control']),bins=40);plt.xlabel('log10(selected jobs / original source-hour count)');plt.ylabel('New groups');save('sampling_fractions.png')
    plt.figure(figsize=(8,4));plt.scatter([w['reference_arrival_rate_per_second'] for w in snapshots],[w['realized_arrival_rate_per_second'] for w in snapshots],s=18)
    lim=[min(w['reference_arrival_rate_per_second'] for w in snapshots),max(w['reference_arrival_rate_per_second'] for w in snapshots)]
    plt.plot(lim,lim,'k--');plt.xscale('log');plt.yscale('log');plt.xlabel('Observed peak-minute rate / second');plt.ylabel('Reconstructed local snapshot rate / second');save('snapshot_rate_fidelity.png')
    plt.figure(figsize=(8,4));examples=rounding['hypothetical_fractional_examples'];plt.bar([str(e['mean_ms']) for e in examples],[e['relative_error_percent'] for e in examples]);plt.xlabel('Hypothetical fractional mean (ms), not actual converted data');plt.ylabel('Ceiling error (%)');plt.title('Published positive means are integer: actual added error = 0 ms');save('rounding_distortion.png')
    print(json.dumps(dict(before=b,after=a,coverage=coverage,snapshot_rate_error_percent=summary(rate_error),shape_tv=summary(shape)),indent=2))


if __name__=='__main__':
    main()
