# Small external Azure-derived pilot

**Coverage gap:** the selected peak-rate snapshot exceeded the prespecified runtime
budget and is excluded from every policy. No completed peak-load evaluation is
claimed. High-load mixed-hour groups were not selected: every group has 2,000 jobs
and even the smallest exceeds 3.8 million proxy CPU milliseconds. Mixed-function
coverage here uses the retained-control cohort. The CPU-budget caps favor shorter,
sparser cases; conclusions do not extend to the omitted high-demand cohorts.

## Review-safe findings

- Saved v5 inference ran without retraining and matched tuned MLFQ on every
  reported metric for all 14 completed workloads. This pilot shows no v5 gain.
- Default MLFQ's descriptive mean score is 0.013182; tuned MLFQ and v5 both score
  0.013776. These use this pilot's fixed five-policy normalization, not historical
  synthetic score bounds. They do not establish population-wide superiority.
- Sparse hourly samples have little contention. Mean workload P95 is zero for
  all policies except Priority RR (0.925 ms); this does not mean every job has
  zero wait, or that the missing peak snapshot is safe.

`reference_labels.json` contains evaluation-only static minimum-score references,
retaining ties within 1e-12. Reproduce them from each workload's CSV scores across
all policies except Dynamic v5. These are simulated references, not observed Azure
outcomes or a new training dataset; no external selection accuracy is reported.

Microsoft Azure Functions 2019 revision 2; Shahrad et al., Serverless in the Wild, USENIX ATC 2020; CC-BY

Fixed selection seed 20261019; 15 attempted, 14 completed workloads. No fitting, tuning, regeneration or rescaling.

Whole-workload selections and pool exclusions: `selection.json` and `protocol.json`; outcomes: `workloads.csv`.

Completed strata: {'low_load': 3, 'medium_load': 3, 'high_rate_control': 3, 'mixed_functions': 3, 'high_load_hour_sample': 2}. Azure cohorts: {'retained_control': 12, 'high_load_hour_sample': 2}.

| Policy | Avg wait ms | Avg response ms | Avg turnaround ms | Mean workload P95 ms | Jobs/ms | Utilization fraction | Weighted score |
|---|---:|---:|---:|---:|---:|---:|---:|
| FCFS | 0.275476 | 0.275476 | 273.293745 | 0.000000 | 0.000086 | 0.001420 | 0.019686 |
| Round Robin | 0.550357 | 0.003881 | 273.568626 | 0.000000 | 0.000086 | 0.001420 | 0.014284 |
| Priority | 0.275476 | 0.275476 | 273.293745 | 0.000000 | 0.000086 | 0.001420 | 0.019686 |
| Priority RR | 1.956626 | 0.838911 | 274.974895 | 0.925000 | 0.000086 | 0.001420 | 0.915403 |
| MLFQ | 0.553095 | 0.001393 | 273.571364 | 0.000000 | 0.000086 | 0.001420 | 0.013182 |
| Tuned MLFQ | 0.551917 | 0.000321 | 273.570186 | 0.000000 | 0.000086 | 0.001420 | 0.013776 |
| Dynamic v5 | 0.551917 | 0.000321 | 273.570186 | 0.000000 | 0.000086 | 0.001420 | 0.013776 |

Unweighted mean over complete workloads; not invocation-weighted or representative Azure performance. Throughput/utilization use simulator start-to-completion, not full source exposure.

Fixed five eligible static-policy bounds within each workload; same weights; NOT comparable to historical six-reference scores.

Eligible static policies only: SJF/SRTF are not part of the realistic reference set. No scheduler settings or score weights changed.

Dynamic v5 inference evaluated: True. External algorithm-selection accuracy: unavailable. No matching fitted six-policy classifier binary; dynamic excursion actions are not comparable to whole-workload static reference labels.

Per-stratum metrics are in `summary.json`; pooled numbers are descriptive only. No policy/model is promoted.

## Limitations

- Daily wall-clock means proxy CPU demand; individual CPU/I/O demand is unavailable.
- Arrivals are reconstructed from minute bins; snapshots assume conditional uniform order statistics, not observed microbursts.
- All priorities are neutral zero and no I/O bursts are supplied by Azure.
- Frozen 2-ms RR quanta, 8/20/40-ms aging and 10-ms dynamic epochs were not calibrated for Azure; synthetic-to-ms feature/domain shift remains.
- Small, CPU-budget-biased purposeful strata; possible source-hour overlap; no significance, population ranking or kernel-validation claims.

Runtime exclusions (not replaced): [{'workload_id': 'azure-refined-d13-0207', 'stratum': 'peak_rate_snapshot', 'reason': 'Prespecified 90-second whole-workload runtime budget exceeded'}].

All protected dataset/model/report checksums match. This is not real CPU scheduler validation.
