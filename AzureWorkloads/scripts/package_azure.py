"""Package validated artifacts, scripts and documentation; exclude raw/extracted data."""
import argparse
import importlib.metadata
import json
from pathlib import Path
import platform
import shutil
import subprocess
import zipfile

from common import ROOT, dump
from extract_azure import sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--output',type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    validation = json.loads((root/'reports/validation_results.json').read_text())
    if not validation.get('passed'):
        raise ValueError('Execute validation before packaging')
    for name,digest in validation['data_sha256'].items():
        if sha256(root/'cleaned'/name)!=digest:
            raise ValueError(f'Data changed after validation: {name}')
    files = []
    for directory in ['cleaned','scripts','reports','tests']:
        files.extend(p for p in (root/directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc')
    files.extend(root/name for name in ['README.md','requirements.txt','requirements.lock','.gitignore'])
    files = sorted(files)
    selection = json.loads((root/'reports/selection_summary.json').read_text())
    extraction = json.loads((root/'reports/extraction_manifest.json').read_text())
    commit = subprocess.run(['git','rev-parse','HEAD'],cwd=root.parent,capture_output=True,text=True).stdout.strip()
    metadata = dict(schema_version=2,dataset='Microsoft Azure Functions 2019',
        documentation='https://github.com/Azure/AzurePublicDataset/blob/master/AzureFunctionsDataset2019.md',
        license='CC-BY (upstream attribution requirement; see README)',
        attribution='Shahrad et al., Serverless in the Wild, USENIX ATC 2020',
        source_archive=extraction['archive'],source_archive_sha256=extraction['archive_sha256'],
        repository_commit=commit,python=platform.python_version(),
        dependencies={name:importlib.metadata.version(name) for name in ['numpy','pandas','matplotlib','scikit-learn']},
        units=dict(arrival_time='integer milliseconds relative to workload absolute_start_ms (hour start or local snapshot start)',
                   absolute_arrival_time='integer milliseconds since start of source day 1',
                   burst_time='ceil(positive daily wall-clock mean in ms), proxy only',
                   source_minute='original one-based column 1..1440'),
        seed=selection['seed'],max_jobs_per_workload=selection['max_jobs'],window_minutes=60,
        job_count=selection['job_count'],workload_count=selection['workload_count'],
        direct_columns=['HashOwner','HashApp','HashFunction','Trigger','day (filename)','source_minute (column name)',
                        'minute invocation counts','Average','Count','Minimum','Maximum','percentile_Average_*'],
        reconstructed_columns=['pid','arrival_time','absolute_arrival_time','burst_time','priority=0',
                               'invocation_ordinal','workload grouping'],
        bookkeeping_columns=['source_file','source_row','duration_row','match_status','duration_status','invocation_status'],
        limitations=['Wall-clock duration is not measured CPU demand','No per-invocation latency or arrival timestamps',
                     'No CPU/I/O phase information','No actual process priorities','No cold-start timing',
                     'Invocation bins are post-execution logs','Hourly samples attenuate absolute arrival rates; local snapshots assume uniform within-minute arrivals',
                     'Selected groups are not population-weighted; source windows can overlap across groups',
                     'Percentiles of interval averages are not sampled as per-invocation percentiles'],
        sampling_cohorts=['retained_control','high_load_hour_sample','high_load_mixed_hour_sample','local_rate_snapshot'],
        sampling_details='Original counts, per-cell fractions/ordinals and snapshot exposures are stored per workload/source',
        rounding_analysis=json.loads((root/'reports/rounding_analysis.json').read_text()),
        comparison=json.loads((root/'reports/before_after_comparison.json').read_text())['coverage'],
        protected_observation_sha256=selection['protected_observation_sha256'],
        file_sha256={str(p.relative_to(root)):sha256(p) for p in files},validation=validation)
    dump(root/'metadata.json',metadata)
    files.append(root/'metadata.json')
    output = args.output or root.parent/'AutoScheduler_Azure_Cleaned.zip'
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as archive:
        for path in sorted(files):
            info = zipfile.ZipInfo('AzureWorkloads/'+str(path.relative_to(root)),date_time=(1980,1,1,0,0,0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            with path.open('rb') as source, archive.open(info,'w',force_zip64=True) as target:
                shutil.copyfileobj(source,target,1024*1024)
    with zipfile.ZipFile(output) as archive:
        failure = archive.testzip()
        if failure:
            raise ValueError(f'ZIP CRC failure: {failure}')
    print(json.dumps(dict(zip=str(output.resolve()),bytes=output.stat().st_size,sha256=sha256(output),
                          files=len(files),crc_validation='passed'),indent=2))


if __name__=='__main__':
    main()
