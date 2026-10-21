"""Refine evaluation selection from immutable cleaned observations, without cleaning."""
import argparse
import copy
import csv
import json
from pathlib import Path
import random

import numpy as np
import pandas as pd

from common import ROOT, KEY, MINUTES, dump, source_seed, snapshot_offsets, summary
from convert_workloads import JOB_FIELDS, PROCESS_FIELDS, reconstruct
from extract_azure import sha256


def apportion(counts, budget, seed):
    """Proportional integer quotas; preserve every active cell when the budget permits."""
    counts=np.asarray(counts,dtype=float)
    if not np.isfinite(counts).all() or (counts<0).any() or (counts!=np.floor(counts)).any():
        raise ValueError('Observed counts must be finite nonnegative integers')
    total=int(counts.sum())
    if budget<1 or total<1:
        raise ValueError('A positive budget and population are required')
    if total<=budget:
        return counts.astype(np.int64)
    flat=counts.ravel()
    ideal=flat*(budget/total)
    allocated=np.floor(ideal).astype(np.int64)
    lower=(flat>0).astype(np.int64) if (flat>0).sum()<=budget else np.zeros_like(allocated)
    allocated=np.maximum(allocated,lower)
    tie=np.random.default_rng(seed).random(len(flat))*1e-10
    while allocated.sum()<budget:
        scores=np.where(allocated<flat,ideal-allocated+tie,-np.inf)
        allocated[int(np.argmax(scores))]+=1
    while allocated.sum()>budget:
        scores=np.where(allocated>lower,allocated-ideal+tie,-np.inf)
        allocated[int(np.argmax(scores))]-=1
    return allocated.reshape(counts.shape)


def sample_sources(sources, budget, seed):
    result=copy.deepcopy(sources)
    if sum(sum(s['counts']) for s in sources)<=budget:
        return result
    # Stable identity ordering makes quotas invariant to caller source ordering.
    result.sort(key=lambda s:(s['day'],*(s[k] for k in KEY)))
    allocations=apportion(np.array([s['counts'] for s in result]),budget,seed)
    for source,quotas in zip(result,allocations):
        rng=random.Random(source_seed(source,seed,'ordinal_sample'))
        source['sampling_method']='minute_stratified_without_replacement'
        source['sampled_counts']=list(map(int,quotas))
        source['sampled_ordinals']=[sorted(rng.sample(range(1,int(n)+1),int(k))) for n,k in zip(source['counts'],quotas)]
        source['within_minute_inclusion_fractions']=[int(k)/int(n) if n else None for n,k in zip(source['counts'],quotas)]
    return result


def snapshot_source(source,budget,seed):
    result=copy.deepcopy(source)
    index=int(np.argmax(source['counts']))
    count=source['counts'][index]
    selected=min(budget,count)
    result['sampling_method']='contiguous_uniform_snapshot'
    result['snapshot']=dict(minute_index=index,selected_count=selected)
    pairs=snapshot_offsets(result,seed)
    minute_start=(source['day']-1)*86400000+(source['start_minute']+index)*60000
    if selected==count:
        origin,exposure=minute_start,60000
    else:
        origin=minute_start+pairs[0][1]
        exposure=pairs[-1][1]-pairs[0][1]+1
    result['sampled_counts']=[selected if i==index else 0 for i in range(len(source['counts']))]
    result['snapshot'].update(first_ordinal=pairs[0][0],minute_sampling_fraction=selected/count,
                              exposure_fraction=exposure/60000)
    return result,origin,exposure


def select_high(candidates,day,seed,maximum):
    high=candidates.loc[candidates['count']>maximum].copy()
    if high.empty:
        return []
    high['tie']=np.random.default_rng(seed+day).random(len(high))
    high['block']=high.start_minute//360
    groups=[]
    for block in range(4):
        pool=high.loc[high.block==block]
        if pool.empty:
            continue
        # Mid-volume and maximum-volume windows expose the old cap bias.
        edges=np.quantile(pool['count'],[1/3,2/3])
        mid=pool.loc[pool['count'].between(*edges)]
        if mid.empty:
            mid=pool
        durations=np.quantile(mid.Average,[1/3,2/3])
        band=np.searchsorted(durations,mid.Average,side='left')
        refined=mid.loc[band==(day+block)%3]
        if len(refined):
            mid=refined
        middle=mid.loc[mid.tie.idxmin()]
        extreme=pool.sort_values(['count','tie'],ascending=[False,True]).iloc[0]
        for row,label in [(middle,'over_cap_middle_volume'),(extreme,'over_cap_extreme_volume')]:
            groups.append(dict(day=day,start_minute=int(row.start_minute),source_rows=[int(row.source_row)],
                cohort='high_load_hour_sample',reasons=[label,f'block_{block}']))
        groups.append(dict(day=day,start_minute=int(extreme.start_minute),source_rows=[int(extreme.source_row)],
            cohort='local_rate_snapshot',reasons=['peak_minute_contiguous_reconstructed_ranks',f'block_{block}']))
        same=high.loc[high.start_minute==extreme.start_minute]
        # Select distinct functions across observed duration ranks at the same source hour.
        same=same.sort_values(['Average','tie']).drop_duplicates('source_row')
        if len(same)>=2:
            indices=sorted(set([0,len(same)//2,len(same)-1]))
            groups.append(dict(day=day,start_minute=int(extreme.start_minute),
                source_rows=[int(same.iloc[i].source_row) for i in indices],
                cohort='high_load_mixed_hour_sample',reasons=['mixed_high_volume_functions',f'block_{block}']))
    return groups


def group_metrics(group,jobs):
    original=np.sum([s['counts'] for s in group['sources']],axis=0)
    sampled=np.zeros(len(original),dtype=np.int64)
    for job in jobs:
        sampled[job['source_minute']-group['start_minute']-1]+=1
    total=int(original.sum())
    group.update(observed_count=total,job_count=len(jobs),observed_minute_counts=original.tolist(),
        sampled_minute_counts=sampled.tolist(),sampling_fraction=len(jobs)/total,
        quiet_fraction=float(np.mean(original==0)),sampled_quiet_fraction=float(np.mean(sampled==0)),
        fano=float(np.var(original)/np.mean(original)),sampled_fano=float(np.var(sampled)/np.mean(sampled)),
        minute_shape_total_variation=float(.5*np.abs(original/total-sampled/len(jobs)).sum()),
        original_hour_arrival_rate_per_second=total/3600,
        realized_arrival_rate_per_second=len(jobs)/(group['exposure_ms']/1000),
        processes=[{k:j[k] for k in PROCESS_FIELDS} for j in jobs])
    if group['cohort']=='local_rate_snapshot':
        source=group['sources'][0]
        index=source['snapshot']['minute_index']
        group['reference_arrival_rate_per_second']=source['counts'][index]/60
    else:
        group['reference_arrival_rate_per_second']=total/3600


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--seed',type=int,default=42)
    parser.add_argument('--max-jobs',type=int,default=2000)
    args=parser.parse_args()
    if args.max_jobs<180 or args.max_jobs>2000 or args.seed<0:
        parser.error('Use 180..2000 jobs (enough for all active cells of a 3-function hour), seed >=0')
    root=args.root
    baseline=root/'reports/baseline'
    protected=json.loads((baseline/'protected_inputs.json').read_text())
    for name,digest in protected.items():
        if sha256(root/name)!=digest:
            raise ValueError(f'Cleaned observations changed: {name}')
    before=json.loads((baseline/'evaluation_workloads.json').read_text())
    if before['seed']!=args.seed or any(len(w['processes'])>args.max_jobs for w in before['workloads']):
        parser.error('Retaining exact controls requires their original seed and a sufficient cap')
    # Discard only stale generated metadata; the immutable baseline retains the old manifest.
    (root/'metadata.json').unlink(missing_ok=True)
    descriptors,pending,coverage=[],[],[]
    current=None
    def finish():
        if not pending:
            return
        table=pd.concat(pending,ignore_index=True)
        high=table.loc[table['count']>args.max_jobs]
        selected=select_high(table,current,args.seed,args.max_jobs)
        descriptors.extend(selected)
        coverage.append(dict(day=current,valid_hour_windows=len(table),positive_hour_windows=int((table['count']>0).sum()),
            usable_invocations=int(table['count'].sum()),over_cap_windows=len(high),
            over_cap_invocations=int(high['count'].sum()),new_groups=len(selected),
            over_cap_size_summary=summary(high['count'])))
        pending.clear()
        print(f'Day {current:02}: selected {len(selected)} high-load groups from {len(high):,} over-cap hours',flush=True)
    with pd.read_csv(root/'cleaned/azure_cleaned.csv',chunksize=1024) as chunks:
        for chunk in chunks:
            for day,data in chunk.groupby('day',sort=False):
                day=int(day)
                if current is not None and current!=day:
                    finish()
                current=day
                data=data.loc[(data.match_status=='usable') & (data.invocation_status=='usable')]
                counts=data[MINUTES].to_numpy(dtype=float).reshape(len(data),24,60)
                valid=np.isfinite(counts).all(axis=2)
                table=pd.DataFrame(dict(source_row=np.repeat(data.source_row.to_numpy(),24),
                    start_minute=np.tile(np.arange(24)*60,len(data)),count=np.nansum(counts,axis=2).ravel(),
                    Average=np.repeat(data.Average.to_numpy(),24)))
                pending.append(table.loc[valid.ravel()])
    finish()
    needed={(g['day'],r) for g in descriptors for r in g['source_rows']}
    rows={}
    with pd.read_csv(root/'cleaned/azure_cleaned.csv',chunksize=1024) as chunks:
        for chunk in chunks:
            mask=[(int(d),int(r)) in needed for d,r in zip(chunk.day,chunk.source_row)]
            for row in chunk.loc[mask].to_dict('records'):
                rows[(int(row['day']),int(row['source_row']))]=row
    groups=copy.deepcopy(before['workloads'])
    for group in groups:
        group.update(cohort='retained_control',exposure_ms=3600000)
    for i,descriptor in enumerate(descriptors,1):
        group=dict(descriptor,workload_id=f'azure-refined-d{descriptor["day"]:02}-{i:04}',window_minutes=60)
        sources=[]
        start=group['start_minute']
        for rowid in group['source_rows']:
            row=rows[(group['day'],rowid)]
            sources.append(dict(day=group['day'],source_row=rowid,duration_row=int(row['duration_row']),
                **{k:row[k] for k in KEY},Trigger=None if pd.isna(row['Trigger']) else row['Trigger'],
                Average=float(row['Average']),start_minute=start,
                counts=[int(row[str(m)]) for m in range(start+1,start+61)]))
        if group['cohort']=='local_rate_snapshot':
            source,origin,exposure=snapshot_source(sources[0],args.max_jobs,args.seed)
            group.update(sources=[source],absolute_start_ms=origin,exposure_ms=exposure)
        else:
            group.update(sources=sample_sources(sources,args.max_jobs,args.seed),
                absolute_start_ms=(group['day']-1)*86400000+start*60000,exposure_ms=3600000)
        groups.append(group)
    with (root/'cleaned/azure_scheduler_jobs.csv').open('w',newline='') as output:
        writer=csv.DictWriter(output,fieldnames=JOB_FIELDS);writer.writeheader()
        for group in groups:
            jobs=reconstruct(group['workload_id'],group['sources'],args.seed,origin_ms=group['absolute_start_ms'])
            if not 0<len(jobs)<=args.max_jobs:
                raise ValueError('Workload exceeds the process cap')
            group_metrics(group,jobs)
            writer.writerows(jobs)
    payload=dict(schema_version=2,seed=args.seed,time_unit='ms',duration_method='ceil_daily_wall_clock_mean_ms',
        max_jobs=args.max_jobs,reconstruction='Retained controls plus explicit minute-stratified samples and conditional uniform contiguous-rank snapshots',workloads=groups)
    dump(root/'cleaned/evaluation_workloads.json',payload)
    previous=json.loads((baseline/'selection_summary.json').read_text())
    previous.update(schema_version=2,seed=args.seed,max_jobs=args.max_jobs,workload_count=len(groups),
        job_count=sum(g['job_count'] for g in groups),size_summary=summary([g['job_count'] for g in groups]),
        burst_proxy_ms=summary([p['burst_time'] for g in groups for p in g['processes']]),
        high_load_days=coverage,retained_control_count=len(before['workloads']),
        cap_only_excluded_windows_after=0,cap_only_excluded_invocations_after=0,
        protected_observation_sha256=protected)
    dump(root/'reports/selection_summary.json',previous)
    print(f'Wrote {previous["job_count"]:,} jobs across {len(groups)} workloads; original controls retained',flush=True)


if __name__=='__main__':
    main()
