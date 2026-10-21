# Dynamic V3 end-to-end demonstration

Status: **SYNTHETIC_DEVELOPMENT_ONLY**. This demonstrates the complete control flow; it is not Linux-kernel performance evidence.

## 1. Model-family bake-off

All families receive the same observed-state features, grouped trace split, policy-cost targets, and configuration budget. Lower is better. A result within 0.5% uses the configured simpler-family tie-break.

| Family | Validation schedule score | Validation action regret | Internal test action regret |
|---|---:|---:|---:|
| Dummy | 0.211921 | 0.006952 | 0.001919 |
| Ridge | 0.163789 | 0.011424 | 0.013726 |
| Decision Tree | 0.211921 | 0.023325 | 0.001919 |
| Random Forest | 0.177576 | 0.023332 | 0.001919 |
| Histogram Gradient Boosting | 0.199825 | 0.026911 | 0.018779 |

Selected family: **Ridge**. Decision Tree best under this run: **False**.
If this value is false, the run does not prove that Decision Tree is the best family; the tree-only Dynamic V3 stage below remains a workflow demonstration.

## 2. Dynamic V3 tree formulation

| Tree | Validation score | P95 response | Starvation |
|---|---:|---:|---:|
| classifier | 0.200705 | 44.192 | 16.667 |
| policy_cost | 0.210202 | 26.617 | 17.000 |

Frozen Dynamic V3 demonstration tree: **classifier**.

## 3. Unseen changing workload

Seed: `9090`. Phases: `cpu_intensive, interactive, batch`.
The router schedules a review every 10 ticks and applies it at the next safe dispatch boundary. A switch must pass confidence, minimum 20-tick dwell, and policy-cost margin checks.

| Policy | Weighted score | Mean response | P95 wait | Starvation |
|---|---:|---:|---:|---:|
| FCFS | 0.431192 | 156.100 | 527.000 | 29 |
| SJF | 0.137993 | 148.667 | 473.650 | 25 |
| SRTF | 0.149254 | 139.100 | 484.200 | 26 |
| Round Robin | 0.230345 | 25.467 | 526.650 | 30 |
| Priority | 0.423333 | 248.667 | 516.300 | 26 |
| Priority RR | 0.768929 | 42.367 | 808.100 | 30 |
| MLFQ | 0.191536 | 13.600 | 519.550 | 30 |
| Dynamic V3 | 0.254691 | 45.767 | 522.350 | 28 |

Dynamic final policy: **MLFQ**. Accepted switches: **8**. Decision P99: **0.250112 ms**.

## Artifacts

- `summary.json`: complete machine-readable report
- `model_family_bakeoff.csv`: five-family comparison
- `tree_variant_comparison.json`: classifier tree versus policy-cost tree
- `decision_log.csv`: every 10-tick review and safety decision
- `gantt.png`: final CPU execution timeline
- `artifacts/dynamic_v3_demo_smoke/models/`: frozen classifier and policy-cost tree bundles
