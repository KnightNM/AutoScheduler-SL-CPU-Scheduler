"""Validate cleaned tables and reconstruct every packaged job without running a scheduler."""
import argparse
from collections import Counter
import csv
import json
import math
from pathlib import Path
import sys

import numpy as np
import pandas as pd

from common import ROOT, KEY, MINUTES, STATS, dump
from convert_workloads import JOB_FIELDS, PROCESS_FIELDS, reconstruct
from extract_azure import sha256


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(root, repo):
    sys.path.insert(0, str(repo))
    from simulator.process import Process
    root = Path(root)
    payload = json.loads((root / 'cleaned/evaluation_workloads.json').read_text())
    cleaning = json.loads((root / 'reports/cleaning_summary.json').read_text())
    selection = json.loads((root / 'reports/selection_summary.json').read_text())
    require(payload['schema_version'] in (1,2) and payload['time_unit']=='ms', 'Schema version or time unit mismatch')
    require(payload['duration_method']=='ceil_daily_wall_clock_mean_ms', 'Unexpected duration interpretation')
    require(payload['seed']==selection['seed'] and payload['max_jobs']==selection['max_jobs'], 'Configuration mismatch')
    workloads = payload['workloads']
    require(bool(workloads), 'No workloads generated')
    require(len({w['workload_id'] for w in workloads})==len(workloads), 'Duplicate workload IDs')
    selected = {(int(w['day']),int(s['source_row'])): s for w in workloads for s in w['sources']}
    found, retained, missing, zero = set(), 0, 0, 0
    last_day, last_row, seen_keys = -1, -1, set()
    expected_columns = ['day','source_file'] + KEY + ['Trigger','source_row'] + MINUTES + [
        'invocation_status'] + STATS + ['duration_row','match_status']
    with pd.read_csv(root / 'cleaned/azure_cleaned.csv',chunksize=1024) as chunks:
        for chunk in chunks:
            require(list(chunk.columns)==expected_columns, 'Cleaned invocation schema mismatch')
            counts = chunk[MINUTES].to_numpy(dtype=float)
            finite = counts[np.isfinite(counts)]
            require(not np.isinf(counts).any() and bool((finite>=0).all()) and bool((finite==np.floor(finite)).all()) and bool((finite<=2**53-1).all()),
                    'Invalid invocation counts remain')
            require(not chunk[KEY].isna().any().any(), 'Missing invocation identifier')
            missing += int(np.isnan(counts).sum()); zero += int((counts==0).sum()); retained += len(chunk)
            for row in chunk[['day','source_file',*KEY,'source_row','invocation_status']].itertuples(index=False,name=None):
                day,file,*rest = row
                *ids,line,status = rest
                day,line = int(day),int(line)
                require(day>=last_day and (day!=last_day or line>last_row), 'Source day/row ordering changed')
                if day!=last_day:
                    seen_keys.clear()
                key = tuple(ids)
                require(key not in seen_keys or status=='conflicting_key', 'Unflagged duplicate invocation key')
                seen_keys.add(key); last_day,last_row = day,line
                require(file==f'invocations_per_function_md.anon.d{day:02}.csv', 'Incorrect invocation source file')
            mask = [(int(d),int(r)) in selected for d,r in zip(chunk.day,chunk.source_row)]
            for row in chunk.loc[mask].to_dict('records'):
                identity = (int(row['day']),int(row['source_row']))
                require(row['match_status']=='usable' and row['invocation_status']=='usable', 'Ineligible source converted')
                # A source row may occur in multiple selected hours; validate every occurrence.
                for w in workloads:
                    if w['day']!=identity[0] or identity[1] not in w['source_rows']:
                        continue
                    source = next(s for s in w['sources'] if s['source_row']==identity[1])
                    require(all(row[key]==source[key] for key in KEY+['Average','duration_row']) and (row['Trigger']==source['Trigger'] or (pd.isna(row['Trigger']) and source['Trigger'] is None)), 'Source identifiers/statistic changed')
                    require(source['start_minute']==w['start_minute'], 'Mixed source windows do not align')
                    start = source['start_minute']
                    observed = [row[str(m)] for m in range(start+1,start+61)]
                    require(observed==source['counts'], 'Minute counts or source minute indexing changed')
                found.add(identity)
    require(found==set(selected), 'Selected source rows missing from cleaned observations')
    total = cleaning['totals']['invocation']
    require(retained==total['retained_rows'], 'Cleaned row count mismatch')
    require(zero==total['zero_cells'], 'Legitimate zeros were lost')
    require(missing==total['missing_cells']+total['invalid_cells'], 'Missing/invalid cells were silently imputed')
    for kind, totals in cleaning['totals'].items():
        require(totals['retained_rows']==totals['original_rows']-totals['duplicates_dropped']-totals['missing_key_rows_dropped'],
                f'{kind}: source row accounting mismatch')
    durations = pd.read_csv(root / 'cleaned/azure_durations_cleaned.csv')
    require(list(durations.columns)==['day','source_file',*KEY,'source_row',*STATS,'duration_status'], 'Duration schema mismatch')
    require(len(durations)==cleaning['totals']['duration']['retained_rows'], 'Duration count mismatch')
    duplicate = durations.duplicated(['day',*KEY],keep=False)
    require(bool((durations.loc[duplicate,'duration_status']=='conflicting_key').all()), 'Ambiguous duration keys unflagged')
    require(not durations.duplicated(['day',*KEY,*STATS]).any(), 'Identical duration duplicates remain')
    numeric = durations[STATS].to_numpy(dtype=float)
    require(not np.isinf(numeric).any() and not (numeric<0).any(), 'Invalid duration measurements remain')
    sample_counts = durations.Count.dropna().to_numpy()
    require(bool((sample_counts>0).all()) and bool((sample_counts==np.floor(sample_counts)).all()), 'Invalid duration sample counts')
    usable = durations.loc[durations.duration_status=='usable']
    require(bool((usable.Average>0).all()) and not usable.Count.isna().any(), 'Usable duration lacks positive mean/sample count')
    require(not ((usable.Minimum>usable.Maximum) | (usable.Average<usable.Minimum) | (usable.Average>usable.Maximum)).any(), 'Usable duration bounds are inconsistent')
    percentile_columns = [s for s in STATS if s.startswith('percentile_')]
    require(not (np.diff(usable[percentile_columns].to_numpy(),axis=1)<0).any(), 'Usable percentiles are inconsistent')
    duration_lookup = durations.set_index(['day','source_row'])
    for w in workloads:
        for source in w['sources']:
            drow = duration_lookup.loc[(source['day'],source['duration_row'])]
            require(drow['duration_status']=='usable', 'Invalid duration used')
            require(all(drow[key]==source[key] for key in KEY+['Average']), 'Duration provenance mismatch')
    pids, count, sizes = set(), 0, []
    with (root / 'cleaned/azure_scheduler_jobs.csv').open(newline='') as f:
        reader = csv.DictReader(f)
        require(reader.fieldnames==JOB_FIELDS, 'Job schema mismatch')
        for w in workloads:
            expected = reconstruct(w['workload_id'],w['sources'],payload['seed'],origin_ms=w['absolute_start_ms'])
            require(expected==reconstruct(w['workload_id'],w['sources'],payload['seed'],origin_ms=w['absolute_start_ms']), 'Seed is not reproducible')
            require(0<len(expected)<=payload['max_jobs'] and len(expected)==w.get('job_count',w['observed_count']), 'Workload size invalid')
            require([{k:j[k] for k in PROCESS_FIELDS} for j in expected]==w['processes'], 'JSON Process records mismatch')
            expected_counts = np.sum([s['counts'] for s in w['sources']],axis=0).tolist()
            require(expected_counts==w['observed_minute_counts'], 'Workload minute aggregation mismatch')
            hour_start=(w['day']-1)*86400000+w['start_minute']*60000
            if w.get('cohort')!='local_rate_snapshot':
                require(w['absolute_start_ms']==hour_start, 'Incorrect day/time units')
            require(w['window_minutes']==60, 'Unsupported window size')
            require(math.isclose(w['quiet_fraction'],sum(c==0 for c in expected_counts)/60), 'Quiet period mismatch')
            minute_counts = Counter()
            for job in expected:
                actual = next(reader,None)
                require(actual=={key:('' if value is None else str(value)) for key,value in job.items()}, 'CSV job differs from reproducible reconstruction')
                require(job['pid'] not in pids, 'Duplicate Process pid')
                pids.add(job['pid'])
                require(0<=job['arrival_time']<w.get('exposure_ms',3600000), 'Negative/out-of-window arrival or incorrect units')
                require(job['absolute_arrival_time']==w['absolute_start_ms']+job['arrival_time'], 'Absolute timestamp mismatch')
                require(job['burst_time']==math.ceil(job['Average']) and job['priority']==0, 'Incorrect burst proxy or priority')
                require((job['absolute_arrival_time']-(w['day']-1)*86400000)//60000==job['source_minute']-1, 'Minute reconstruction mismatch')
                process = Process(**{key:job[key] for key in PROCESS_FIELDS})
                require(process.cpu_bursts==(job['burst_time'],) and process.io_bursts==(), 'Invented CPU/I/O trace')
                minute_counts[job['source_minute']] += 1
                count += 1
            wanted=w.get('sampled_minute_counts',expected_counts)
            require([minute_counts[m] for m in range(w['start_minute']+1,w['start_minute']+61)]==wanted,
                    'Reconstruction does not preserve sampled counts')
            if payload['schema_version']==2:
                validate_sampling(w,payload['seed'],payload['max_jobs'])
            sizes.append(len(expected))
        require(next(reader,None) is None, 'Unexpected extra jobs')
    require(count==selection['job_count'] and len(workloads)==selection['workload_count'], 'Selection summary mismatch')
    if payload['schema_version']==2:
        baseline=json.loads((root/'reports/baseline/evaluation_workloads.json').read_text())
        controls={w['workload_id']:w for w in workloads if w['cohort']=='retained_control'}
        require(set(controls)=={w['workload_id'] for w in baseline['workloads']}, 'Original controls lost')
        for old in baseline['workloads']:
            require(controls[old['workload_id']]['processes']==old['processes'], 'Original control Process values changed')
        for name,digest in selection['protected_observation_sha256'].items():
            require(sha256(root/name)==digest, f'Original cleaned observations changed: {name}')
    # Packages can be validated without raw/extracted data; verify packaged hashes if present.
    metadata_path = root / 'metadata.json'
    verified_hashes = 0
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text())
        for name,digest in metadata.get('file_sha256',{}).items():
            require(sha256(root/name)==digest, f'Checksum mismatch: {name}')
            verified_hashes += 1
    return dict(passed=True,cleaned_invocation_rows=retained,cleaned_duration_rows=len(durations),
        missing_invocation_cells=missing,zero_invocation_intervals=zero,traceable_selected_source_rows=len(found),
        scheduler_jobs=count,workloads=len(workloads),minimum_workload_size=min(sizes),maximum_workload_size=max(sizes),
        data_sha256={name:sha256(root/'cleaned'/name) for name in [
            'azure_cleaned.csv','azure_durations_cleaned.csv','azure_scheduler_jobs.csv','evaluation_workloads.json']},
        checks=['schemas','missing_values','duplicate_keys','invalid_durations','row_accounting',
                'source_order','minute_counts','time_units','source_to_output_traceability',
                'seeded_reproducibility','workload_sizes','Process_construction','no_invented_io','bounded_stratified_sampling','contiguous_snapshot_exposure','retained_baseline_controls','immutable_cleaned_observations'],
        package_hashes_checked=verified_hashes)


def validate_sampling(w,seed,maximum):
    from refine_workloads import sample_sources, snapshot_source
    original=sum(sum(s['counts']) for s in w['sources'])
    require(w['observed_count']==original, 'Original invocation context count changed')
    require(math.isclose(w['sampling_fraction'],w['job_count']/original), 'Incorrect sampling fraction')
    sampled=np.asarray(w['sampled_minute_counts'])
    observed=np.asarray(w['observed_minute_counts'])
    require(bool((sampled<=observed).all()) and bool((sampled[observed==0]==0).all()), 'Invented invocations/quiet-minute arrivals')
    require(math.isclose(w['sampled_quiet_fraction'],float(np.mean(sampled==0))), 'Sampled quiet fraction mismatch')
    require(math.isclose(w['minute_shape_total_variation'],float(.5*np.abs(observed/original-sampled/w['job_count']).sum())), 'Shape distortion metric mismatch')
    originals=[{k:v for k,v in s.items() if k not in ['sampling_method','sampled_counts','sampled_ordinals','within_minute_inclusion_fractions','snapshot']} for s in w['sources']]
    if w['cohort']=='local_rate_snapshot':
        expected,origin,exposure=snapshot_source(originals[0],maximum,seed)
        require(w['sources']==[expected] and w['absolute_start_ms']==origin and w['exposure_ms']==exposure, 'Contiguous snapshot/exposure not reproducible')
    else:
        require(w['exposure_ms']==3600000, 'Hourly temporal scale changed')
        expected=sample_sources(originals,maximum,seed)
        require(w['sources']==expected, 'Stratified sampling/quotas not reproducible')
        require(bool((sampled[observed>0]>0).all()), 'Active minute lost despite sufficient sampling budget')
    require(math.isclose(w['realized_arrival_rate_per_second'],w['job_count']/(w['exposure_ms']/1000)), 'Realized arrival rate mismatch')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--repo',type=Path,default=ROOT.parent)
    parser.add_argument('--write-report',action='store_true')
    args = parser.parse_args()
    result = validate(args.root,args.repo)
    if args.write_report:
        dump(args.root/'reports/validation_results.json',result)
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
