"""Inspect all CSVs, preserve daily wide observations, and join without ambiguous keys."""
import argparse
from collections import Counter
import csv
import gc
from pathlib import Path

import numpy as np
import pandas as pd

from common import ROOT, KEY, MINUTES, STATS, INV_COLUMNS, DUR_COLUMNS, append_csv, day_of, dump


def clean_frame(frame, kind, day, filename):
    """Validate a daily table; blank corrupt cells with an explicit audit, never impute."""
    columns = INV_COLUMNS if kind == 'invocation' else DUR_COLUMNS
    if list(frame.columns) != columns:
        raise ValueError(f'Schema mismatch in {filename}: {list(frame.columns)}')
    original = len(frame)
    frame = frame.copy()
    frame['source_row'] = np.arange(2, original + 2)  # CSV line, including header
    audit = []
    duplicate = frame.duplicated(columns, keep='first')
    missing_key = frame[KEY].isna().any(axis=1) | frame[KEY].eq('').any(axis=1)
    for mask, reason in [(duplicate, 'identical_duplicate'), (missing_key & ~duplicate, 'missing_identifier')]:
        for row in frame.loc[mask, 'source_row']:
            audit.append(dict(source_file=filename, source_row=int(row), column='',
                              original_value='', action='drop_row', reason=reason))
    frame = frame.loc[~duplicate & ~missing_key].copy()
    conflict = frame.duplicated(KEY, keep=False)
    numeric = MINUTES if kind == 'invocation' else STATS
    before = frame[numeric]
    values = before.apply(pd.to_numeric, errors='coerce').to_numpy(dtype=float, copy=True)
    missing = before.isna().to_numpy()
    invalid = (~np.isfinite(values) & ~missing) | (values < 0)
    if kind == 'invocation':
        invalid |= (np.isfinite(values) & (values != np.floor(values))) | (values > 2**53 - 1)
    else:
        ci = numeric.index('Count')
        invalid[:, ci] |= np.isfinite(values[:, ci]) & ((values[:, ci] != np.floor(values[:, ci])) | (values[:, ci] <= 0))
    for row, col in zip(*np.where(invalid)):
        audit.append(dict(source_file=filename, source_row=int(frame.iloc[row].source_row),
                          column=numeric[col], original_value=str(before.iloc[row, col]),
                          action='blank_cell', reason='invalid_numeric_measurement'))
    values[invalid] = np.nan
    frame = pd.concat([frame.drop(columns=numeric), pd.DataFrame(values, index=frame.index, columns=numeric)], axis=1)
    if kind == 'duration':
        # True bounds and ordered percentiles are invariants; do not trim by magnitude.
        percentiles = frame[[s for s in STATS if s.startswith('percentile_')]].to_numpy()
        inconsistent = ((frame.Minimum > frame.Maximum) | (frame.Average < frame.Minimum)
                        | (frame.Average > frame.Maximum)).to_numpy(copy=True)
        inconsistent |= np.any(np.diff(percentiles, axis=1) < 0, axis=1)
        status = np.full(len(frame), 'usable', dtype=object)
        status[(frame.Average.isna() | (frame.Average <= 0) | frame.Count.isna()).to_numpy()] = 'nonpositive_or_missing_mean'
        status[invalid.any(axis=1) | inconsistent] = 'invalid_statistics'
        status[conflict.to_numpy()] = 'conflicting_key'
        frame['duration_status'] = status
        for row in np.flatnonzero(inconsistent):
            audit.append(dict(source_file=filename, source_row=int(frame.iloc[row].source_row),
                              column='statistics', original_value='', action='exclude_conversion',
                              reason='inconsistent_duration_statistics'))
    else:
        frame['invocation_status'] = np.where(conflict, 'conflicting_key', 'usable')
    frame.insert(0, 'day', day)
    frame.insert(1, 'source_file', filename)
    report = dict(kind=kind, file=filename, day=day, original_rows=original, retained_rows=len(frame),
                  duplicates_dropped=int(duplicate.sum()), missing_key_rows_dropped=int((missing_key & ~duplicate).sum()),
                  conflicting_key_rows=int(conflict.sum()), missing_cells=int(missing.sum()),
                  missing_by_column=dict(zip(numeric, map(int, missing.sum(axis=0)))),
                  invalid_cells=int(invalid.sum()), corrected_rows=int(invalid.any(axis=1).sum()),
                  zero_cells=int((values == 0).sum()), dtypes={str(k): str(v) for k,v in before.dtypes.items()})
    if kind == 'duration':
        report['status_counts'] = dict(Counter(status))
    return frame, report, audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    root = args.root
    (root / 'cleaned').mkdir(parents=True, exist_ok=True)
    (root / 'reports').mkdir(parents=True, exist_ok=True)
    outputs = ['azure_cleaned.csv', 'azure_durations_cleaned.csv']
    for name in outputs:
        (root / 'cleaned' / name).unlink(missing_ok=True)
    reports, audits, inventory = [], [], []
    paths = sorted((root / 'extracted').rglob('*.csv'))
    inv_paths = {day_of(p): p for p in paths if p.name.startswith('invocations_')}
    dur_paths = {day_of(p): p for p in paths if p.name.startswith('function_durations_')}
    if not inv_paths or not dur_paths:
        raise ValueError('Invocation and duration CSVs are required')
    # Memory tables are inspected but never used as fabricated I/O/CPU observations.
    for p in paths:
        if p.name.startswith('app_memory_'):
            data = pd.read_csv(p)
            inventory.append(dict(file=p.name, role='memory_inspection_only', rows=len(data),
                                  columns=list(data.columns), missing_cells=int(data.isna().sum().sum()),
                                  dtypes={k: str(v) for k,v in data.dtypes.items()}))
    for day in sorted(set(inv_paths) | set(dur_paths)):
        duration = None
        if day in dur_paths:
            p = dur_paths[day]
            duration, report, audit = clean_frame(pd.read_csv(p), 'duration', day, p.name)
            reports.append(report); audits.extend(audit)
            append_csv(duration, root / 'cleaned/azure_durations_cleaned.csv')
            inventory.append(dict(file=p.name, role='duration', rows=report['original_rows'], columns=DUR_COLUMNS))
        if day not in inv_paths:
            continue
        p = inv_paths[day]
        inv, report, audit = clean_frame(pd.read_csv(p), 'invocation', day, p.name)
        reports.append(report); audits.extend(audit)
        inventory.append(dict(file=p.name, role='invocation', rows=report['original_rows'], columns=INV_COLUMNS))
        counts = inv[MINUTES].to_numpy()
        report['observed_invocations'] = int(np.nansum(counts))
        report['missing_intervals'] = int(np.isnan(counts).sum())
        report['zero_intervals'] = int((counts == 0).sum())
        minute_total = np.nansum(counts, axis=0)
        report['minute_totals'] = list(map(int, minute_total))
        del counts
        if duration is None:
            for stat in STATS:
                inv[stat] = np.nan
            inv['duration_row'] = np.nan
            inv['match_status'] = 'missing_duration'
            report['duration_only_rows'] = 0
        else:
            unique = duration.loc[~duration.duplicated(KEY, keep=False), KEY + STATS + ['source_row', 'duration_status']]
            unique = unique.rename(columns={'source_row': 'duration_row'})
            inv = inv.merge(unique, on=KEY, how='left', sort=False, validate='many_to_one')
            conflicts = pd.MultiIndex.from_frame(duration.loc[duration.duplicated(KEY, keep=False), KEY])
            ambiguous = pd.MultiIndex.from_frame(inv[KEY]).isin(conflicts)
            inv['match_status'] = inv.pop('duration_status').fillna('missing_duration')
            inv.loc[ambiguous, 'match_status'] = 'ambiguous_duration'
            inv.loc[inv.invocation_status != 'usable', 'match_status'] = 'ambiguous_invocation'
            ikeys = pd.MultiIndex.from_frame(inv[KEY])
            report['duration_only_rows'] = int((~pd.MultiIndex.from_frame(duration[KEY]).isin(ikeys)).sum())
            # Independent logging systems need not have identical invocation totals.
            report['duration_count_disagreement_rows'] = int((inv.Count.notna() & (inv[MINUTES].sum(axis=1, min_count=1440) != inv.Count)).sum())
        report['match_counts'] = {str(k): int(v) for k,v in inv.match_status.value_counts().items()}
        append_csv(inv, root / 'cleaned/azure_cleaned.csv')
        print(f'Day {day:02}: {len(inv):,} invocation rows; {report["match_counts"]}', flush=True)
        del inv, duration
        gc.collect()
    with (root / 'reports/cleaning_audit.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['source_file','source_row','column','original_value','action','reason'])
        writer.writeheader(); writer.writerows(audits)
    dump(root / 'reports/inspection.json', inventory)
    totals = {kind: {key: sum(r[key] for r in reports if r['kind'] == kind) for key in
                    ['original_rows','retained_rows','duplicates_dropped','missing_key_rows_dropped',
                     'conflicting_key_rows','missing_cells','invalid_cells','corrected_rows','zero_cells']}
              for kind in ['invocation','duration']}
    dump(root / 'reports/cleaning_summary.json', dict(totals=totals, files=reports))


if __name__ == '__main__':
    main()
