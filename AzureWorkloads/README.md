# Refined Azure Functions 2019 evaluation workloads

This handoff refines evaluation selection only. The original cleaned observation
tables are unchanged, with their previous SHA-256 hashes verified during selection
and validation. No extraction or cleaning was repeated, and no scheduler source,
models, synthetic datasets, training or model evaluation was changed or run.

The files are external-trace-derived inputs for controlled scheduling experiments,
not measured CPU demand or a reproduction of production Azure execution.

## Teammate integration

Extract `AutoScheduler_Azure_Cleaned.zip` at an existing AutoScheduler repository
root. Preserve any existing `AzureWorkloads/` you need before replacing artifacts.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r AzureWorkloads/requirements.txt
python AzureWorkloads/scripts/validate_azure.py
```

The delivered environment used Python 3.12; `requirements.lock` records exact
versions. Normal requirements resolve compatible versions for Python 3.10+.

Construct Process objects without running any scheduler/model:

```python
import json
from pathlib import Path
from simulator.process import Process

payload = json.loads(Path(
    "AzureWorkloads/cleaned/evaluation_workloads.json"
).read_text())
workload = next(w for w in payload["workloads"]
                if w["cohort"] == "local_rate_snapshot")
processes = [Process(**row) for row in workload["processes"]]
assert len(processes) == workload["job_count"] <= 2000
```

Use `reports/workload_manifest.csv` to choose by cohort, day, source hour, rates,
sampling fractions, counts and reasons. Report each cohort separately; unweighted
pooling does not estimate invocation-weighted Azure performance. Scheduler quantum,
aging and feature thresholds must be calibrated to **1 tick = 1 ms** in a later
experiment. This phase does not run that experiment or reuse a trained selector.

## What changed and why

The old selector rejected a whole function-hour whenever its count exceeded 2,000,
only 0.556 arrivals/second averaged over an hour. Thus a small, heavy-volume tail of
255,612 usable function-hours containing 11,792,466,817 invocations was ineligible:
94.37% of all recorded calls. The refinement makes positive, usable hours eligible
for bounded sampling rather than excluding them solely for volume.

That is **an eligibility improvement, not 100% traffic coverage**. The actual
materialized suite is a small subset. The comparison distinguishes eligibility,
selected source-hour context volume, unique reconstructed occurrence labels and
jobs including overlap. The cleaned tables retain every original observation.

The refined file has 510 groups and 520,408 jobs:

| Cohort | Groups | Purpose |
|---|---:|---|
| retained_control | 286 | Original Process inputs unchanged: low/medium rates, burstiness, quiet periods, short/long means, mixed functions |
| high_load_hour_sample | 112 | Bounded single-function samples of middle and extreme over-cap source hours |
| high_load_mixed_hour_sample | 56 | Same-hour samples combining observed short/middle/long mean-duration functions |
| local_rate_snapshot | 56 | Short, contiguous reconstructed-rank snapshots approximating peak-minute rates |

All 14 days and all four six-hour blocks per day are covered. Groups contain
1–2,000 processes. In each day/block, new selection targets a seeded middle-volume
over-cap hour (rotating duration strata), the maximum-volume hour, a same-hour
mixture and a peak-minute local snapshot. Selection is purposeful coverage, not a
population probability sample; global selection weights are not known.

## Two high-load views

An hour sample keeps the original physical hour and its observed minute pattern.
Its rate is reduced by sampling. A local snapshot changes the observation window
to a short contiguous interval under an explicit within-minute reconstruction,
providing approximately the original minute's local rate. These serve different
controls and must not be interpreted interchangeably.

### Minute-stratified hour samples

- The group budget is apportioned across function/minute cells proportionally to
  original counts, with seeded tie breaking and integer quotas.
- Every positive cell gets at least one job when the budget permits. There are at
  most 180 cells for a three-function hour; the CLI requires a budget of at least
  180. Original zero cells remain zero.
- Quotas sum exactly to the cap when population exceeds it. Invocation ordinals are
  sampled without replacement uniformly within each cell, using O(cap) memory.
  Full large populations are never expanded.
- Offsets are deterministic SHA-256-based uniform integer milliseconds in the
  original minute, keyed by seed, day, owner, app, function, minute and ordinal.
  Ordinals are conceptual source occurrence identities, not observed timestamps.
- Lower bounds overrepresent rare cells. Exact original counts, sampled counts,
  sampled ordinals and per-cell selected/original inclusion fractions are stored.
  Conditional cell inclusion fractions do not correct purposeful hour selection.

Normalized minute-shape total variation quantifies shape distortion. Binary quiet
patterns remain unchanged for the hourly views. Absolute arrival rates and raw
Fano factors are attenuated; no time compression is applied to hide this.

### Conditional uniform local snapshots

The busiest minute of an extreme source hour has N observed invocations. Choose a
seeded random block of K=min(cap,N) consecutive conceptual invocation ranks. Under
N independent uniform within-minute arrivals, joint order statistics for those K
ranks can be generated using Dirichlet gaps without constructing all N timestamps.
This preserves approximately the peak-minute rate while bounding process count.

Offsets are floored to integer milliseconds. When K<N, the exposure begins at the
first selected timestamp and ends one millisecond after the last. When K=N, the
whole minute is retained. Source minute inclusion fraction K/N, exposure fraction,
first ordinal, source-hour fraction and exact exposure/origin are recorded. Rate
error against the source minute is reported; finite sampling, conditional window
selection and millisecond rounding affect it. Boundary ties can omit other
conceptual arrivals sharing the same rounded millisecond.

**Subminute arrival variation is unavailable.** These snapshots are conditional
uniform reconstructions, not observed microbursts. Every job remains traceable to
an observed function/day/minute count. Snapshot and hour-sample reconstructions
are alternative views of the same aggregated data and can overlap. Group them by
source function/day/hour in any future split. Never infer a snapshot's true quiet
periods from its source-hour `sampled_minute_counts`: those bins show where the
snapshot lies in the source hour, with unsampled minutes outside its exposure.

## Schema and time units

`evaluation_workloads.json` uses schema version 2. `processes` entries contain only
`pid`, `arrival_time`, `burst_time`, `priority`, suitable for `Process(**row)`.
`azure_scheduler_jobs.csv` retains the prior column schema and adds new rows. Its
first 72,408 jobs reproduce the original controls unchanged.

| Field | Meaning |
|---|---|
| HashOwner, HashApp, HashFunction, Trigger | Original Azure identifiers/trigger; missing optional trigger stays missing |
| day | Relative source day from filename; no absolute calendar timestamp invented |
| source_minute | Original 1-based count column, 1–1440 |
| source_row, duration_row | CSV line numbers including the header, linked within day |
| Average | Published daily wall-clock mean in milliseconds |
| burst_time | ceil(positive Average), integer ms; wall-clock CPU-burst proxy |
| priority | Neutral 0; no actual priorities are supplied by Azure |
| arrival_time | Reconstructed ms relative to group `absolute_start_ms` |
| absolute_arrival_time | Reconstructed ms since the start of source day 1 |
| absolute_start_ms | Source hour start for hour views; explicit interval start for snapshots |
| exposure_ms | Duration of the represented hour or local snapshot interval |
| observed_count / observed_minute_counts | Full original source-hour context count(s), including unsampled invocations |
| job_count / sampled_minute_counts | Selected jobs and their footprint in the original 60 minute bins |
| sampling_fraction | job_count / full original source-hour context count |
| reference_arrival_rate_per_second | Original hourly rate, or original peak-minute rate for local snapshots |
| realized_arrival_rate_per_second | job_count / exposure seconds |
| cpu_bursts, io_bursts | Omitted: Process supplies one proxy burst and an empty I/O tuple |

For snapshots, `quiet_fraction`, `sampled_quiet_fraction`, Fano and minute-shape
fields describe the source-hour context/footprint, not subminute behavior inside
the exposure. Snapshot rate fidelity is the relevant local metric. The reports
compare quiet periods and minute shape only for hourly cohorts.

## Rounding audit

The positive published daily means in this archive are already integer
milliseconds. The actual added ceiling error is **0 ms / 0%**, including short
positive means. The reports quantify counts in <=1 ms, 1–4 ms and 4–10 ms bins and
verify every generated job. Published zero means remain excluded from positive
bursts rather than being fabricated as 1 ms.

This does not establish zero error against actual execution times. Unrounded means
and the upstream quantization convention are unavailable. For hypothetical positive
fractional means, ceiling 0.1 ms to 1 ms adds 900%, and 1.2 to 2 ms adds 66.7%.
Those examples are sensitivity analysis, not fabricated Azure jobs. Wall-clock
execution and daily averages still cannot recover true CPU bursts or individual
invocation duration distributions.

## Reproduce only the refinement

Raw and extracted data are not needed. Keep the original cleaned files and the
immutable `reports/baseline/` artifacts. The baseline contains the previous JSON,
job CSV, summaries, manifest and metadata as historical records, plus protected
input hashes. Its old metadata is not the current package manifest.

```bash
python AzureWorkloads/scripts/refine_workloads.py --seed 42 --max-jobs 2000
python -m unittest discover -s AzureWorkloads/tests -p test_refinement.py -v
python AzureWorkloads/scripts/validate_azure.py --write-report
python AzureWorkloads/scripts/report_azure.py
python AzureWorkloads/scripts/package_azure.py
```

The original-control seed must remain 42 and the cap must accommodate every
original control. Selection can be rerun reproducibly from the saved baseline;
existing derived outputs are replaced and stale current metadata is removed.
Both observation tables are checked against their saved SHA-256 hashes first.
Do not run the legacy `convert_workloads.py` CLI to regenerate the refined suite:
its original v1 selector is retained for historical reproducibility; its shared
reconstruction function supports both schemas.

Stages accept `--root /path/to/AzureWorkloads`. Validator accepts `--repo`; package
accepts `--output`. Defaults are relative to the script location, with no machine
paths. Dependencies are unchanged: repository NumPy/Matplotlib plus pandas.

## Reports, checks and packaging

- `before_after_comparison.json`: exact old/refined distributions and distinct
  coverage denominators, plus per-cohort summaries.
- `rounding_analysis.json`: rounding errors and short-duration counts.
- `workload_statistics.md`: investigation, comparison, sampling assumptions,
  distortion and controlled-evaluation assessment.
- `data_quality_report.md`: retained historical cleaning quality and current checks.
- `workload_manifest.csv`: cohort, count, source/exposure, rates and fractions.
- `plots/`: original distributions plus old/new comparisons, sampling fractions,
  snapshot rate fidelity and rounding sensitivity.
- `validation_results.json`: executed checks and validated data hashes.
- `metadata.json`: source attribution, versions, cohorts, units, comparison,
  rounding and SHA-256 checksums of packaged files.

Validation rechecks the cleaned schemas/records, source and duration provenance,
original and selected counts, quotas, unique ordinals, fixed-seed reproducibility,
integer time units and exposure, exact original controls, unchanged observation
hashes and successful construction of every Process. Tests exercise huge-count
sampling without population expansion, quiet-bin preservation, local rates,
short-duration rounding and rejection of tampered sampling fractions. Fixture tests
write small, explicitly constructed tables and do not extract or clean the dataset.

Packaging verifies hashes recorded by validation, then builds
`AutoScheduler_Azure_Cleaned.zip` at the repository root and checks ZIP CRCs. It
includes cleaned observations, both evaluation versions, scripts, dependencies,
reports, plots, tests and metadata; raw/extracted data and caches are excluded.

## Evaluation scope and attribution

This is sufficiently broad for controlled external-trace-derived comparisons when
cohorts and assumptions are explicit. It is not a probability-weighted sample or a
production-accurate Azure CPU workload. Do not infer population-wide algorithm
rankings from pooled results. CPU/I/O demand, true subminute starts, individual
latencies, actual priorities, dependencies, cold starts and multicore state remain
unavailable. Scheduler/model experiments require a separate phase.

Source: [Microsoft Azure Functions 2019, revision 2](https://github.com/Azure/AzurePublicDataset/blob/master/AzureFunctionsDataset2019.md).
The trace is CC-BY. Preserve attribution to Mohammad Shahrad et al., “Serverless in
the Wild: Characterizing and Optimizing the Serverless Workload at a Large Cloud
Provider,” USENIX ATC 2020. Original archive/member checksums and discovered schemas
remain in `reports/extraction_manifest.json`, `inspection.json`, and
`cleaning_summary.json`. Invocation bins are post-execution logs and wall-clock
statistics exclude cold starts; percentile columns describe interval averages.

## Snapshot method reference

Uniform order-statistic spacings have a flat Dirichlet law; see the proof of
Proposition 4.1 in [Chazal et al., *Choosing the Parameter of the Fermat Distance*,
Appendix A](https://arxiv.org/pdf/2311.18663#page=16). The implementation aggregates
the unused outer gaps. For zero-based starting rank r and K retained ranks among
N arrivals, it draws gaps with parameters
`(r+1, 1 repeated K-1 times, N-r-K+1)` and uses the first K cumulative sums.
This is the implementation's application of that spacing law under its explicit
uniform-arrival assumption. Sampling uses
[NumPy Generator.dirichlet](https://numpy.org/doc/stable/reference/random/generated/numpy.random.Generator.dirichlet.html),
which generates normalized Gamma variates. No Azure measurements establish this
within-minute law; it is a stated reconstruction model.
