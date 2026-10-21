# Azure generalization: controlled development baseline

**Azure-derived simulation only. No new model fitted or promoted. Holdout remains untouched.**

Dataset: Microsoft Azure Functions 2019 revision 2, CC-BY; attribution to Mohammad Shahrad et al., “Serverless in the Wild,” USENIX ATC 2020. Existing cleaned schema-2 seed-42 input contains 510 workloads and 520,408 reconstructed jobs. Source archive/member provenance remains in `AzureWorkloads/reports/`; no source data was regenerated. Published daily wall-clock means are CPU-demand proxies, not measured CPU bursts. Within-minute arrivals are reconstructed under the documented uniform-arrival assumption, not observed OS arrivals.

## What the original equality meant

The original 14 completed workloads reproduced their saved mean waiting, response and turnaround exactly. The fitted v5 artifact passed its feature/configuration contract and was invoked 7,878 times. It made 221 accepted policy transitions, but only 92 reviews had at least two ready jobs. Every workload had aggregate unfinished work at fewer than 5% of arrivals. No raw prediction selected No Switch and no compatibility/confidence fallback occurred. Equality therefore does not demonstrate learned generalization: most departures were blocked or had no scheduling choice to improve.

Inspection of the unchanged depth-3 cost tree explains the proposals: it splits on only **completed burst variance, ready count, and arrival quiet time**, despite accepting 19 observed inputs. None of its seven leaves chooses No Switch as the first minimum. Four near-zero-variance leaves favor Priority; one heterogeneous/recent-arrival leaf has all costs tied at zero and proposes FCFS by action ordering. The other two heterogeneous leaves predict Priority benefits below the .005 margin. Thus a raw Priority/FCFS proposal is not evidence of useful adaptation. Neutral-priority and many other range violations do not directly change tree routing because those inputs are unused. See `model_tree_audit.json`.

The raw proposals were screened by first-service protection (4,004 reviews), observed arrival risk (998), and cost margin (2,655); 114 ordinary transitions and 107 expiry returns were accepted. These reasons are not independent causal effect estimates. Per-workload arrivals, burst dispersion, pending-work contention, simulated duration, review counts, raw proposals, disposition, and full active-policy intervals are in `original_pilot_diagnosis.json`.

## Protocol and coverage

Selected **17 whole development workloads**, seed 20261020, one per connected owner/app/function group. 76 of 303 provenance components remain reserved; 73 are genuinely untouched after excluding three historical-pilot groups. Selection uses metadata, pending-work thresholds and predeclared CPU-demand caps, never policy outcomes. The selected IDs differ from the original 15 pilot IDs. Two selected source components were seen in that pilot (peak and high-load mixed); their reuse is explicitly diagnostic, not independent validation. All related hours, days and mixed snapshots stay on one side of the reserve boundary. The initial reserve mistakenly included three historically examined components. `untouched_holdout_manifest.json` explicitly subtracts them without changing the frozen development selection. The remaining reserve has no historical-pilot or current-investigation policy outcomes. Only two independent function components underlie all 56 peak snapshots.

One tick = 1 ms; input jobs, reconstructed arrivals and daily wall-clock-mean duration proxies are unchanged. Five fixed eligible static policies provide within-workload normalization, separate from historical synthetic six-policy scores. Weights remain waiting .30, response .25, turnaround .20, utilization .15, throughput .10. Parameters, source hashes, pools, cap exclusions and reserved IDs are in `selection_manifest.json`. RR uses quantum 2; Priority-RR uses quantum 2/aging 8/cost 1; default MLFQ uses (2,4,8)/aging 20/cost 0; tuned MLFQ and v5 use (1,2,4)/aging 40/cost 0. Policy-specific costs are retained, not silently equalized. There is no added generic adaptive reconfiguration charge; this limits any claimed benefit. The static Priority policy has no aging and all Azure priorities are neutral, so FCFS/Priority equivalence is expected.

Inherited policy-specific overhead confounds a pure algorithm-only comparison involving Priority-RR; the principal v5/default/tuned-MLFQ comparisons all use zero charged context-switch cost. Fixed 2-ms quanta and 10/20-ms review/dwell periods are not rescaled for these much longer wall-clock proxies. That unit-consistent but distribution-mismatched choice is explicit, not a tuning parameter.

Throughput is completed jobs divided by simulator makespan; utilization is a fraction over that same simulated window, not the complete Azure source hour. P95 is computed within each workload and averaged across workloads. Starvation retains the report-only waiting-time > 3 × proxy CPU-demand criterion. Source-disjoint function groups can still share calendar periods or applications; bootstrap intervals do not model that dependence.

Each policy has a fixed 20-second wall-time budget. **12/17 workloads completed all seven policies**. All failures remain in `workloads.csv`; none are replaced. A weighted score is unavailable if any fixed reference times out. The following averages use the common all-policy-complete subset and cannot summarize the difficult censored workloads.

| Policy | Complete/selected | Score | Wait ms | Response ms | P95 ms | Turnaround ms | Jobs/ms | Utilization | Starvation/workload | Switches/workload | Mean workload P99 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| FCFS | 17/17 | 0.208333 | 16263.735389 | 16263.735389 | 32729.837500 | 20017.265389 | 0.000079 | 0.113454 | 47.416667 | 0.000000 | Unavailable |
| Round Robin | 17/17 | 0.076304 | 32298.883515 | 4.905751 | 18.158333 | 36052.413515 | 0.000079 | 0.113454 | 73.083333 | 0.000000 | Unavailable |
| Priority | 17/17 | 0.208333 | 16263.735389 | 16263.735389 | 32729.837500 | 20017.265389 | 0.000079 | 0.113454 | 47.416667 | 0.000000 | Unavailable |
| Priority RR | 16/17 | 0.793043 | 53886.885684 | 13.554873 | 38.425000 | 57640.415684 | 0.000079 | 0.112711 | 153.833333 | 0.000000 | Unavailable |
| MLFQ | 17/17 | 0.076778 | 32311.521600 | 2.221562 | 12.875000 | 36065.051600 | 0.000079 | 0.113454 | 74.166667 | 0.000000 | 0.003238 |
| Tuned MLFQ | 15/17 | 0.076082 | 32262.493432 | 0.301921 | 2.912500 | 36016.023432 | 0.000079 | 0.113454 | 73.333333 | 0.000000 | 0.003394 |
| Dynamic v5 | 12/17 | 0.132043 | 16304.782740 | 991.355316 | 2197.908333 | 20058.312740 | 0.000079 | 0.113454 | 44.166667 | 494.333333 | 1.157657 |

Only MLFQ exposes a static ready-selection timing hook; other static latencies are unavailable, not zero (see `measurement_notes.json`). Dynamic latency includes feature extraction, model, safeguards and queue rebuild. Dynamic prediction observers add diagnostic overhead. These are simulator/controller timings, not Linux scheduling performance.

## Paired comparisons and gates

Strongest static score on the common completed development subset: **Tuned MLFQ**. This conditional comparator is not a holdout-selected deployment recommendation. Differences below are v5 minus comparator; lower is better. Intervals use 10,000 paired workload resamples, seed 2027, one workload per provenance component. Small, capped, censored development samples support only exploratory uncertainty.

| Comparator | Metric | Pairs | Mean difference | 95% CI |
|---|---|---:|---:|---|
| FCFS | weighted_score | 12 | -0.076290 | [-0.134997, -0.022872] |
| FCFS | p95_response_ms | 12 | -30531.929167 | [-87062.700000, -465.385208] |
| FCFS | starvation | 12 | -3.250000 | [-16.333333, 6.583333] |
| Round Robin | weighted_score | 12 | 0.055739 | [-0.045736, 0.199157] |
| Round Robin | p95_response_ms | 12 | 2179.750000 | [244.141667, 5068.803437] |
| Round Robin | starvation | 12 | -28.916667 | [-69.750000, -0.750000] |
| Priority | weighted_score | 12 | -0.076290 | [-0.134997, -0.022872] |
| Priority | p95_response_ms | 12 | -30531.929167 | [-87062.700000, -465.385208] |
| Priority | starvation | 12 | -3.250000 | [-16.333333, 6.583333] |
| Priority RR | weighted_score | 12 | -0.661000 | [-0.847890, -0.411424] |
| Priority RR | p95_response_ms | 12 | 2159.483333 | [221.808333, 5045.779167] |
| Priority RR | starvation | 12 | -109.666667 | [-286.175000, -0.833333] |
| MLFQ | weighted_score | 12 | 0.055265 | [-0.046089, 0.198590] |
| MLFQ | p95_response_ms | 12 | 2185.033333 | [245.037500, 5076.608229] |
| MLFQ | starvation | 12 | -30.000000 | [-72.250000, -0.833333] |
| Tuned MLFQ | weighted_score | 12 | 0.055961 | [-0.045447, 0.199345] |
| Tuned MLFQ | p95_response_ms | 12 | 2194.995833 | [257.868646, 5092.239896] |
| Tuned MLFQ | starvation | 12 | -29.166667 | [-70.416667, -0.750000] |

Frozen gate thresholds are unchanged; conditional results do not compensate for missing coverage or untouched-holdout evidence.

- conditional_primary_score_ci_upper_lt_zero: **fail / not established**
- conditional_primary_p95_ci_upper_le_zero: **fail / not established**
- conditional_primary_mean_starvation_le_zero: **pass**
- completed_workload_max_routing_p99_strictly_lt_10ms: **pass**
- conditional_rr_score_ci_upper_le_zero: **fail / not established**
- conditional_rr_p95_ci_upper_lt_zero: **fail / not established**
- all_selected_workloads_complete: **fail / not established**
- independent_untouched_holdout_improvement_established: **fail / not established**
- promoted: **fail / not established**

## Workload-family results

| Stratum | Selected | All-policy complete | v5 score / P95 ms | Tuned MLFQ score / P95 ms |
|---|---:|---:|---|---|
| peak_rate_snapshot | 1 | 0 | Unavailable | Unavailable |
| mixed_high_hour | 1 | 0 | Unavailable | Unavailable |
| mixed_function_control | 1 | 1 | 0.153182 / 0.000 | 0.142882 / 0.000 |
| sustained_arrivals | 3 | 2 | 0.079611 / 1792.725 | 0.073408 / 0.000 |
| high_contention | 3 | 2 | 0.012279 / 8049.550 | 0.160675 / 17.475 |
| medium_contention | 4 | 3 | 0.415851 / 2230.117 | 0.100643 / 0.000 |
| low_contention | 4 | 4 | 0.000000 / 0.000 | 0.000000 / 0.000 |

Exact workload-level better/tied/worse IDs and every reported metric are in `summary.json` and `workloads.csv`. Family results are descriptive; single-workload strata do not support credible family confidence intervals.

On the 12 common completed workloads, v5 has a lower weighted score on three workloads (`azure-d13-0255`, `azure-d07-0132`, `azure-d10-0191`), ties four and worsens five versus tuned MLFQ. P95 improves on none, ties six and worsens six. Thus the three weighted-score wins are not safety-qualified wins. Mean workload P95 is 2197.908333 ms versus 2.912500 ms; score is 0.132043 versus 0.076082. Mean accepted transitions rise to 494.333 per workload. These values describe the completed subset only.

## Representative confirmed response mechanism

`representative_trace.json` retains a diagnostic replay of `azure-d07-0132` (25 jobs), including every review, each process arrival/first dispatch, and timeline prefixes under both policies. At 2,715,262 ms, the controller accepts Priority with one ready job, no unserved jobs, 27 ms of observed service and 27 ms since arrival. There is no completed burst history. Apart from the unused neutral-priority feature, this departure state is inside the training min/max ranges. Thirteen jobs then arrive while Priority completes the current non-preemptive burst. The first legal MLFQ return is 2,731,966 ms: **16,704 ms after departure**, with 13 unserved jobs and oldest first-service wait 15,279 ms. A representative arrival at 2,716,687 ms waits until 2,731,966 ms for first service; tuned MLFQ dispatches it at arrival. Workload P95 is 15,498.2 ms under v5 versus zero under tuned MLFQ.

This is a dispatch-boundary limitation, not missing inference or a failed return rule: the nominal 20-ms target horizon is not a preemption timer for Priority/FCFS. The guard sees no pressure at departure and cannot inspect future arrivals or true remaining burst. The synthetic diagnostic regression test preserves this exact limitation on a tiny two-job example. Longer observed-history admission rules could be researched, but would not protect this first-burst departure without stronger evidence or more conservative action eligibility. Simply normalizing unused features or removing guards does not address the confirmed mechanism.

## Supported mechanisms and justified changes

- **Low contention:** confirmed for the original pilot; output equality persisted despite real inference and transitions. High hourly invocation count alone was an inadequate selection descriptor.
- **Distribution mismatch:** v5 trained on counts 3/6/12/24/48, priorities 1–5, short synthetic bursts and I/O. Azure has neutral priority 0, up to 2,000 ready jobs, much longer duration proxies and no observed I/O. `training_feature_bounds.json` uses training groups only; `baseline_decisions.json` records per-feature range violations for complete and partial runs. Range violations are diagnostics, not calibrated uncertainty or inference inputs.
- **Guards versus learned intent:** raw predictions, cost vectors, accepted events, competing-ready reviews and rejection counts are saved separately. The original equality was neither absent inference nor a learned No Switch action. Removing first-service or arrival safeguards would not be justified by this evidence.
- **Runtime bottleneck:** bounded pre-change cProfile on the formerly timed-out peak identifies repeated ready-list minimum scans, sorting all MLFQ entries before aging eligibility, neutral-priority arithmetic, and dynamic exact-statistic feature extraction. Only two exact shortcuts were implemented: filter aging eligibility before sorting; return effective priority 1 immediately when already saturated. Dispatch ordering, aging timestamps, costs, features and model decisions are unchanged. Preserved-source equivalence tests compare complete timelines including I/O, arrivals, aging, nonzero overhead and routing safety. The remaining linear scans and feature costs still limit large queues; no unverified heap or feature rewrite was attempted.
- **Bounded profiling after the shortcuts:** in equal 8-second partial cProfile windows, Priority-RR ready selections increase from 11,882 to 26,884, default MLFQ from 15,136 to 23,432, and dynamic dispatches from 6,525 to 8,000. MLFQ aging cumulative time falls from 3.474 to .957 seconds; dynamic aging from 1.548 to .345 seconds. This is single-run instrumented progress, not a repeated end-to-end speedup estimate; every profiled run remains incomplete. Both original and post-change partial profiles are retained. The shortcuts do not solve large-queue replay.
- **Other hypotheses:** no evidence of compatibility fallback; generic switching cost is absent rather than a measured cause. Dwell, late non-preemptive reviews and admission guards constrain possible adaptation, but no controlled ablation establishes that relaxing them would safely improve Azure tails. Static comparisons show available alternatives; they are not finite-horizon counterfactual switch labels. No causal contribution is assigned without such evidence.

## Decision

**Do not promote Dynamic ML. Retain v5 as the experimental research candidate and tuned MLFQ as the existing simulator recommendation.** No new model or hyperparameter was selected: this development investigation does not establish a generalizable, safety-preserving model correction, and heavy-workload censoring prevents a representative overall ranking. The reserved Azure evaluation groups were deliberately not consumed. No before/after model improvement is claimed; runtime equivalence is the only implemented correction. Default MLFQ remains an important comparator, not a reason to change the frozen research configuration.

Further model work would first require efficient semantically equivalent large-queue replay, then development-only feasible-action labels grouped by provenance and a frozen untouched evaluation. Real I/O and OS contention cannot be recovered from these proxies. The smallest controller research question is whether non-preemptive departures should require a validated observed-history burst-risk bound. Merely restricting this fitted tree to preemptive actions would collapse it to MLFQ, because none of its leaves selects RR/Priority-RR; it cannot establish a strict improvement. This requires new development evidence, not a guard removal. Do not fit missing I/O or true remaining CPU as features. Azure-derived simulation cannot establish real-kernel superiority.

## Reproduction and preservation

Use a fresh output path for any deliberate rerun; completed diagnosis/baseline files refuse overwrite. Commands: `.venv/bin/python -m autoscheduler.azure_generalization diagnose`, `.venv/bin/python -m autoscheduler.azure_generalization profile`, `.venv/bin/python -m autoscheduler.azure_generalization_evaluation`, `.venv/bin/python -m autoscheduler.azure_generalization_report`. Supply `--output results/<fresh-directory>` consistently to rerun without overwriting this experiment. The first three consume development simulation time; the final command reads saved results only. All source datasets, model artifacts, historical reports, dashboard and frozen protocols are preserved. Verification and preservation hashes are recorded in `verification.json`. No frontend changes, training, push or merge.
