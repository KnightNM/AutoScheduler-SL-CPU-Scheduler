"""Select observed hourly windows and reconstruct every invocation in selected windows."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import random

import numpy as np
import pandas as pd

from common import ROOT, KEY, MINUTES, dump, summary

PROCESS_FIELDS = ['pid', 'arrival_time', 'burst_time', 'priority']
JOB_FIELDS = ['workload_id'] + PROCESS_FIELDS + [
    'absolute_arrival_time','day','source_minute','invocation_ordinal','source_row','duration_row',
    'HashOwner','HashApp','HashFunction','Trigger','Average','duration_method','time_unit']


def reconstruct(workload_id, sources, seed, origin_ms=None):
    jobs = []
    for source in sources:
        average = source['Average']
        if not isinstance(average, (int, float)) or not math.isfinite(average) or average <= 0:
            raise ValueError('A positive observed mean is required')
        for index, count in enumerate(source['counts']):
            if not isinstance(count, (int, float)) or not math.isfinite(count) or count < 0 or count != int(count):
                raise ValueError('Counts must be observed nonnegative integers')
            minute = source['start_minute'] + index + 1  # original 1..1440 column name
            identity = ':'.join(map(str, [seed,source['day'],*(source[k] for k in KEY),minute]))
            rng = random.Random(int.from_bytes(hashlib.sha256(identity.encode()).digest(), 'big'))
            if source.get('sampling_method') == 'minute_stratified_without_replacement':
                ordinals = source['sampled_ordinals'][index]
                if len(ordinals)!=len(set(ordinals)) or any(i<1 or i>count for i in ordinals):
                    raise ValueError('Invalid sampled invocation ordinal')
                pairs = [(ordinal,int.from_bytes(hashlib.sha256(f'{identity}:{ordinal}'.encode()).digest(),'big')%60000) for ordinal in ordinals]
            elif source.get('sampling_method') == 'contiguous_uniform_snapshot':
                if index != source['snapshot']['minute_index']:
                    continue
                from common import snapshot_offsets
                pairs = snapshot_offsets(source,seed)
            else:
                pairs = list(enumerate(sorted(rng.randrange(60000) for _ in range(int(count))),1))
            for ordinal, offset in pairs:
                absolute = (source['day']-1)*86400000 + (minute-1)*60000 + offset
                arrival = index*60000+offset if origin_ms is None else absolute-origin_ms
                jobs.append(dict(workload_id=workload_id,
                    pid=f'{workload_id}:r{source["source_row"]}:m{minute}:i{ordinal}',
                    arrival_time=arrival, burst_time=math.ceil(average), priority=0,
                    absolute_arrival_time=absolute,
                    day=source['day'], source_minute=minute, invocation_ordinal=ordinal,
                    source_row=source['source_row'], duration_row=source['duration_row'],
                    **{key: source[key] for key in KEY}, Trigger=source['Trigger'], Average=average,
                    duration_method='ceil_daily_wall_clock_mean_ms', time_unit='ms'))
    return sorted(jobs, key=lambda job: (job['arrival_time'], job['pid']))


def choose_windows(candidates, day, seed, maximum):
    """Balance days and six-hour blocks; select by measured rates/durations and extremes."""
    rng = np.random.default_rng(seed + day)
    candidates = candidates.copy()
    candidates['tie'] = rng.random(len(candidates))
    eligible = candidates.loc[candidates['count'].between(1, maximum)].copy()
    if eligible.empty:
        return [], dict(day=day, eligible_windows=0)
    rate_edges = np.quantile(eligible['count'], [1/3,2/3])
    duration_edges = np.quantile(eligible.Average, [1/3,2/3])
    eligible['rate_band'] = np.searchsorted(rate_edges, eligible['count'], side='left')
    eligible['duration_band'] = np.searchsorted(duration_edges, eligible.Average, side='left')
    eligible['block'] = eligible.start_minute // 360
    chosen = {}

    def add(row, reason):
        identity = (int(row.source_row),int(row.start_minute))
        if identity not in chosen:
            chosen[identity] = dict(day=day, start_minute=identity[1], window_minutes=60,
                source_rows=[identity[0]], reasons=[], observed_count=int(row['count']),
                quiet_fraction=float(row.quiet), fano=float(row.fano), mean_ms=float(row.Average))
        chosen[identity]['reasons'].append(reason)

    for block in range(4):
        for band, name in enumerate(['low','medium','high']):
            pool = eligible.loc[(eligible.block == block) & (eligible.rate_band == band)]
            # Rotate duration strata through day/block/rate combinations.
            target = (day+block+band) % 3
            refined = pool.loc[pool.duration_band == target]
            if len(refined):
                pool = refined
            if len(pool):
                add(pool.loc[pool.tie.idxmin()], f'{name}_rate_block_{block}')
    for column, ascending, reason in [('Average',True,'short_duration'),('Average',False,'long_duration'),
                                     ('fano',False,'bursty'),('quiet',False,'quiet_periods'),
                                     ('count',False,'high_process_count')]:
        row = eligible.sort_values([column,'tie'], ascending=[ascending,True]).iloc[0]
        add(row, reason)
    groups = list(chosen.values())
    # Mixed groups combine up to three different functions observed in the SAME hour.
    small = eligible.loc[eligible['count'] <= maximum//3]
    for block in range(4):
        pool = small.loc[small.block == block]
        starts = pool.groupby('start_minute').size()
        starts = starts[starts >= 3].index.to_list()
        if not starts:
            continue
        start = int(rng.choice(starts))
        at_hour = pool.loc[pool.start_minute == start]
        rows, used = [], set()
        for band in range(3):
            matches = at_hour.loc[(at_hour.duration_band == band) & ~at_hour.source_row.isin(used)]
            if len(matches):
                row = matches.loc[matches.tie.idxmin()]
                rows.append(row); used.add(int(row.source_row))
        if len(rows) >= 2:
            groups.append(dict(day=day, start_minute=start, window_minutes=60,
                source_rows=[int(row.source_row) for row in rows], reasons=['mixed_observed_durations'],
                observed_count=int(sum(row['count'] for row in rows))))
    return groups, dict(day=day, candidate_windows=len(candidates), eligible_windows=len(eligible),
        zero_windows=int((candidates['count']==0).sum()),
        over_cap_windows=int((candidates['count']>maximum).sum()),
        over_cap_invocations=int(candidates.loc[candidates['count']>maximum,'count'].sum()),
        rate_tertiles_jobs_per_hour=list(map(float,rate_edges)),
        duration_tertiles_ms=list(map(float,duration_edges)),
        candidate_size_summary=summary(candidates['count']),
        candidate_fano_summary=summary(candidates.fano))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--max-jobs', type=int, default=2000)
    args = parser.parse_args()
    if args.max_jobs < 3 or args.seed < 0:
        parser.error('--max-jobs must be >=3 and --seed nonnegative')
    root = args.root
    groups, coverage, pending = [], [], []
    current_day = None
    histogram_edges = np.array([0,1,2,5,10,20,50,100,200,500,1000,2000,5000,10000,100000,1000000,2**53],dtype=float)
    histogram = np.zeros(len(histogram_edges)-1,dtype=np.int64)
    unusable_rows = missing_windows = 0

    def finish():
        if pending:
            frame = pd.concat(pending, ignore_index=True)
            selected, stats = choose_windows(frame, current_day, args.seed, args.max_jobs)
            groups.extend(selected); coverage.append(stats)
            pending.clear()
            print(f'Selected day {current_day:02}: {len(selected)} workload groups', flush=True)

    # Two bounded-memory passes: candidate summaries, then only selected source rows.
    for chunk in pd.read_csv(root / 'cleaned/azure_cleaned.csv', chunksize=1024):
        for day, data in chunk.groupby('day', sort=False):
            day = int(day)
            if current_day is not None and day != current_day:
                finish()
            current_day = day
            all_counts = data[MINUTES].to_numpy(dtype=float)
            histogram += np.histogram(all_counts[np.isfinite(all_counts)], bins=histogram_edges)[0]
            usable = (data.match_status == 'usable') & (data.invocation_status == 'usable')
            unusable_rows += int((~usable).sum())
            data = data.loc[usable]
            counts = data[MINUTES].to_numpy(dtype=float).reshape(len(data),24,60)
            valid = np.isfinite(counts).all(axis=2)
            missing_windows += int((~valid).sum())
            totals = np.nansum(counts,axis=2)
            means = totals/60
            variances = np.nanvar(counts,axis=2)
            fano = np.divide(variances,means,out=np.zeros_like(means),where=means>0)
            table = pd.DataFrame(dict(day=day,
                source_row=np.repeat(data.source_row.to_numpy(),24),
                start_minute=np.tile(np.arange(24)*60,len(data)),count=totals.ravel(),
                Average=np.repeat(data.Average.to_numpy(),24),
                quiet=(counts==0).mean(axis=2).ravel(),fano=fano.ravel()))
            pending.append(table.loc[valid.ravel()])
    finish()
    needed = {(g['day'],r) for g in groups for r in g['source_rows']}
    sources = {}
    for chunk in pd.read_csv(root / 'cleaned/azure_cleaned.csv', chunksize=1024):
        mask = [(int(d),int(r)) in needed for d,r in zip(chunk.day,chunk.source_row)]
        for row in chunk.loc[mask].to_dict('records'):
            sources[(int(row['day']),int(row['source_row']))] = row
    workloads, all_sizes, all_bursts = [], [], []
    jobs_path = root / 'cleaned/azure_scheduler_jobs.csv'
    with jobs_path.open('w',newline='') as output:
        writer = csv.DictWriter(output,fieldnames=JOB_FIELDS); writer.writeheader()
        for index, group in enumerate(groups,1):
            wid = f'azure-d{group["day"]:02}-{index:04}'
            selected_sources = []
            for rowid in group['source_rows']:
                row = sources[(group['day'],rowid)]
                start = group['start_minute']
                selected_sources.append(dict(day=group['day'],source_row=rowid,
                    duration_row=int(row['duration_row']), **{key:row[key] for key in KEY},
                    Trigger=None if pd.isna(row['Trigger']) else row['Trigger'],Average=float(row['Average']),start_minute=start,
                    counts=[int(row[str(m)]) for m in range(start+1,start+61)]))
            jobs = reconstruct(wid,selected_sources,args.seed)
            if len(jobs) != group['observed_count'] or len(jobs)>args.max_jobs:
                raise ValueError('Selection count mismatch')
            writer.writerows(jobs)
            totals = np.sum([s['counts'] for s in selected_sources],axis=0)
            group.update(workload_id=wid,sources=selected_sources,
                absolute_start_ms=(group['day']-1)*86400000 + group['start_minute']*60000,
                observed_minute_counts=totals.tolist(), quiet_fraction=float(np.mean(totals==0)),
                fano=float(np.var(totals)/np.mean(totals)),
                processes=[{k:job[k] for k in PROCESS_FIELDS} for job in jobs])
            workloads.append(group); all_sizes.append(len(jobs)); all_bursts.extend(j['burst_time'] for j in jobs)
    dump(root / 'cleaned/evaluation_workloads.json',dict(schema_version=1,seed=args.seed,time_unit='ms',
        duration_method='ceil_daily_wall_clock_mean_ms',max_jobs=args.max_jobs,
        reconstruction='Seeded uniform integer offsets within each observed minute; counts preserved exactly',
        workloads=workloads))
    dump(root / 'reports/selection_summary.json',dict(seed=args.seed,max_jobs=args.max_jobs,
        workload_count=len(workloads),job_count=sum(all_sizes),size_summary=summary(all_sizes),
        burst_proxy_ms=summary(all_bursts),unusable_function_day_rows=unusable_rows,
        missing_windows_excluded=missing_windows,days=coverage,
        minute_count_histogram=dict(edges=histogram_edges.tolist(),counts=histogram.tolist())))
    print(f'Wrote {sum(all_sizes):,} jobs in {len(workloads)} groups',flush=True)


if __name__ == '__main__':
    main()
