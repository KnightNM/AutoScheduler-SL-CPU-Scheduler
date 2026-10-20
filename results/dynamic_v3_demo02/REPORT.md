# Dynamic V3 end-to-end demonstration

Status: **SYNTHETIC_DEVELOPMENT_ONLY**. This demonstrates the complete control flow; it is not Linux-kernel performance evidence.

## 1. Model-family bake-off

All families receive the same observed-state features, grouped trace split, policy-cost targets, and configuration budget. Lower is better. A result within 0.5% uses the configured simpler-family tie-break.

| Family | Validation schedule score | Validation action regret | Internal test action regret |
|---|---:|---:|---:|
| Dummy | 0.162973 | 0.008352 | 0.011888 |
| Ridge | 0.143103 | 0.005457 | 0.005816 |
| Decision Tree | 0.120669 | 0.004216 | 0.004394 |
| Random Forest | 0.126164 | 0.003888 | 0.004612 |
| Histogram Gradient Boosting | 0.140503 | 0.004523 | 0.004257 |

Selected family: **Decision Tree**. Decision Tree best under this run: **True**.
If this value is false, the run does not prove that Decision Tree is the best family; the tree-only Dynamic V3 stage below remains a workflow demonstration.

## 2. Dynamic V3 tree formulation

| Tree | Validation score | P95 response | Starvation |
|---|---:|---:|---:|
| classifier | 0.119128 | 31.593 | 15.317 |
| policy_cost | 0.128198 | 73.526 | 14.500 |

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
| Dynamic V3 | 0.251820 | 33.433 | 523.650 | 30 |

Dynamic final policy: **Priority**. Accepted switches: **8**. Decision P99: **0.318302 ms**.

## Artifacts

- `summary.json`: complete machine-readable report
- `model_family_bakeoff.csv`: five-family comparison
- `tree_variant_comparison.json`: classifier tree versus policy-cost tree
- `decision_log.csv`: every 10-tick review and safety decision
- `gantt.png`: final CPU execution timeline
- `artifacts/dynamic_v3_demo02/models/`: frozen classifier and policy-cost tree bundles
