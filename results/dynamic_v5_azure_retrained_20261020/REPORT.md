# Exact-v5 Azure retraining: one development experiment

Azure Functions 2019 reconstructed arrivals and wall-clock CPU-demand proxies; simulator evidence, not Linux measurements.
30 fixed provenance groups: train 18/216 states, validation 6/72, test 6/72. Test has 115 processes; two test groups were previously inspected. Entire comparison is non-independent development evidence. Final 73-group holdout untouched.
Original v5 six outputs, 19 features, depth 3, leaf 10, seed 9701; margin .005 and controller unchanged. Missing FCFS/Priority labels completed at identical saved states; all four existing target heads verified. One fit, no tuning. Mean-cost dummy uses training means.

## Scheduling means
Policy | Score | Wait ms | Response ms | P95 ms | Turnaround ms | Starvation | Accepted total
---|---:|---:|---:|---:|---:|---:|---:
Original v5 | 0.04166667 | 9.04716981 | 9.04716981 | 86.06666667 | 1005.30431267 | 0.00000000 | 190
Azure-retrained v5 | 0.02752916 | 18.10062893 | 0.00000000 | 0.00000000 | 1014.35777179 | 0.00000000 | 2
Tuned MLFQ | 0.02752916 | 18.10062893 | 0.00000000 | 0.00000000 | 1014.35777179 | 0.00000000 | 0

## Regression (six outputs pooled)
Split | MAE | RMSE | R² | Dummy MAE | Dummy RMSE | Dummy R²
---|---:|---:|---:|---:|---:|---:
train | 0.0004349390475 | 0.003415462888 | 0.1129917783 | 0.000348392496 | 0.003625095572 | 0.0007654882731
validation | 0.0009830395594 | 0.008049622954 | -0.1593578756 | 0.0006779573869 | 0.007484353985 | -0.002247726535
test | 0.0002453069321 | 0.001121759625 | -9.425418689 | 9.674624552e-05 | 0.0003558694915 | -0.04924138425

Coverage: {'Original v5': {'completed_workloads': 6, 'timeouts': 0, 'accepted_switches': 190}, 'Azure-retrained v5': {'completed_workloads': 6, 'timeouts': 0, 'accepted_switches': 2}, 'Tuned MLFQ': {'completed_workloads': 6, 'timeouts': 0, 'accepted_switches': 0}}. Maximum candidate routing P99: 3.041620 ms.
Frozen score/P95/starvation/latency/coverage checks: {'strict_score_improvement_vs_tuned': False, 'p95_nonregression': True, 'starvation_nonregression': True, 'routing_p99_lt_10ms': True, 'complete_coverage': True}. No promotion; tuned MLFQ remains recommended.
Paired confidence intervals and per-workload reasons are saved in results.json and workload_results.json. All protected hashes verified. No frontend changes.

Per-workload verification: retrained v5 equals tuned MLFQ on score, waiting, response, P95, turnaround and starvation in all six workloads, despite two accepted policy transitions. No measurable switching benefit. Mean score is 33.93% lower than original v5 on valid paired inputs; waiting and turnaround regress versus original v5. Test R² is negative and worse than the training-mean dummy; no predictive generalization claim is supported.
