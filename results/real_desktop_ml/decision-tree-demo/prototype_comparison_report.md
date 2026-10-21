# Prototype Action-Cost Bake-off Report

## Status

Development-only offline replay screening. This is not evidence of Linux kernel scheduler performance.

## Data

- Label provenance: `pilot_offline_replay_development_only`
- Action rows (train / validation / locked test): 3500 / 585 / 1180
- Traces (train / validation / locked test): 6 / 1 / 2
- Profiles: `['compression', 'cpu']`
- Processes / events: 25 / 2590010
- Seeds: `{'split': 7001, 'model_tuning': 7002, 'bootstrap': 7003, 'generation': []}`
- Cleaning: completed traces are anonymized before feature extraction; action rows are group-split by application, scenario, and capture session.
- Limitation: synthetic data tests the pipeline only and cannot establish a real scheduler result.

## Feature method

At each decision time, every feature is calculated only from events strictly before that time. The model receives these observed-history features plus a one-hot proposed action:

`arrivals_seen`, `ready_count`, `blocked_count`, `running_count`, `wait_mean_ms`, `wait_p95_ms`, `observed_service_mean_ms`, `observed_service_variance_ms2`, `completed_burst_mean_ms`, `completed_burst_variance_ms2`, `io_returns`, `priority_mean`, `priority_variance`, `context_switches`, `wakeups`, `cpu_busy_fraction`.

## Selection

- Model: **Ridge** with `{"alpha": 0.01}`
- Validation realized cost: `0.000000`
- Locked-test realized cost: `0.000000`

The model receives an observed state plus one proposed action, predicts that action's cost, then selects the action with the smallest prediction.

## Locked-test comparators

| Choice | Mean offline replay cost |
| --- | ---: |
| Fixed FCFS | 0.750000 |
| Fixed Round Robin | 0.001179 |
| Fixed Priority | 0.750000 |
| Fixed Priority RR | 0.255207 |
| Fixed MLFQ | 0.000000 |
| Per-state oracle | 0.000000 |
| Selected Ridge | 0.000000 |

## Model comparison

Cost MAE and R² evaluate cost prediction. Action-selection accuracy is agreement with the lowest-cost action for each observed state; it is not a classifier training accuracy.

| Model | Validation cost | Locked-test cost | Cost MAE | Cost R² | Oracle-action agreement | P99 ms | Selected |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Dummy | 0.685690 | 0.750000 | 0.308525 | -0.02382965765073841 | 0.000 | 0.089667 | No |
| Ridge | 0.000000 | 0.000000 | 0.379499 | -1.0489882557663641 | 1.000 | 0.520542 | Yes |
| Decision Tree | 0.000000 | 0.000000 | 0.286773 | -0.21291044619005595 | 1.000 | 0.109417 | No |
| Random Forest | 0.000000 | 0.000000 | 0.268659 | -0.21975569198560096 | 1.000 | 5.758875 | No |
| Histogram Gradient Boosting | 0.000000 | 0.000049 | 0.246823 | -0.011734859106435236 | 0.958 | 10.824083 | No |

## Interpretation

This synthetic dataset exercises the full report pipeline. Its results are not a real-workload or Linux-kernel claim.
