# Refined workload statistics and comparison

## Why the original cap excluded most invocation volume

The old selector filtered entire function-hours before sampling. Its 2,000-job limit is only 0.555556 arrivals/second averaged over an hour. Just 255,612 hours (3.594% of positive usable hours) contain 11,792,466,817 invocations (94.37% of all recorded invocations). The volume distribution is highly concentrated; a small share of busy hours dominates invocation counts. Eligibility filtering therefore removed that tail rather than sampling it.

## Before versus after

| Measure | Original | Refined |
|---|---:|---:|
| Workloads | 286 | 510 |
| Jobs (including source overlaps across groups) | 72,408 | 520,408 |
| Processes/group: median / P95 / max | 20 / 1983 / 2000 | 751.5 / 2000 / 2000 |
| Realized arrivals/second: median / P95 / max | 0.00555556 / 0.550833 / 0.555556 | 0.20875 / 1659.13 / 2503.13 |
| Burst proxy (ms): median / P95 / max | 482 / 5776 / 1.80041e+06 | 840 / 149039 / 1.80041e+06 |
| Unique reconstructed source occurrences | 72,047 | 520,007 |
| Selected source-hour context volume / all calls | 0.000577% | 2.511999% |
| Actual unique sampled occurrences / all calls | 0.000577% | 0.004161% |
| All recorded invocations omitted from the small suite | 99.999423% | 99.995839% |
| Invocation volume ineligible solely due to cap | 94.37% | 0% |

**The last row is an eligibility change, not 100% traffic coverage.** Only a small, bounded subset is materialized. Context volume counts unique selected source-hours including their unsampled invocations; it is not the number of jobs reproduced. Source occurrences can overlap between groups; counts are deduplicated using day/source-row/minute/ordinal. Invocation ordinals are reconstructed identities, not observed timestamps.

| Cohort | Groups | Jobs | Median jobs/group | Median realized rate/s | Median proxy ms |
|---|---:|---:|---:|---:|---:|
| high_load_hour_sample | 112 | 224,000 | 2000 | 0.555556 | 935.5 |
| high_load_mixed_hour_sample | 56 | 112,000 | 2000 | 0.555556 | 92 |
| local_rate_snapshot | 56 | 112,000 | 2000 | 1654.94 | 1641 |
| retained_control | 286 | 72,408 | 20 | 0.00555556 | 482 |

## Sampling design and distortion

All 286 original controls are retained with identical Process values, preserving low/medium arrivals, bursty and quiet hours, mixed functions, short/long durations and temporal variation. For each available day and six-hour block, additions target one seeded middle over-cap volume window and the maximum-volume window, rotating observed mean-duration strata. Each block also adds a same-hour mixture of short/middle/long duration functions and a local snapshot from the extreme hour. Selection is purposeful coverage; no population inclusion probability or global inverse weighting is claimed.

Hourly samples apportion at most 2,000 jobs across function/minute cells. Proportional integer quotas use seeded tie breaking and a one-job lower bound for every originally active cell when feasible (at most 180 cells here). Individual invocation ordinals are then sampled uniformly without replacement within each cell. Original zero cells stay zero. All active cells remain active; low-count cells are overrepresented by the lower bound. Each cell stores its exact selected/original fraction; the overall group fraction is selected jobs/original source-hour count. Conditional cell inclusion weights do not correct the purposeful choice of hours/functions.

For sampled hours, normalized minute-shape total variation: median 0.00401154, P95 0.00707834, maximum 0.0109216. This is half the L1 distance between original and sampled minute proportions; 0 means identical shape. Raw Fano factors shrink with thinning and must not be read as preserved absolute burstiness.

Local snapshots select the busiest minute of an extreme source hour. Given N observed invocations, a seeded random block of K consecutive reconstructed invocation ranks is sampled. Joint uniform order statistics are generated using Dirichlet gaps in O(K) memory; the full N arrivals are never expanded. Times are floored to integer milliseconds. If K=N the entire minute is retained; otherwise the exposure runs from the first selected timestamp to one millisecond after the last. Snapshot per-minute inclusion fraction and exposure fraction are recorded separately from the fraction of the entire source hour represented. Boundary ties can omit other conceptual arrivals with the same rounded millisecond. Arrival origins differ by cohort and are explicit.

Snapshot realized-vs-original peak-minute rate error: median -0.823519%, P95 4.36443%, minimum -4.87%, maximum 6.13421%. Finite order-statistic variation, conditioning on K ranks, and millisecond boundary rounding explain departures. This is not a measurement of within-minute arrival behavior.

## Duration units and rounding

Both arrivals and bursts use **1 tick = 1 ms**. Burst = ceil(positive published daily Average in ms). No time compression or change to the previous burst mapping is introduced. These are wall-clock proxies, never true CPU burst measurements.

Of 651,505 positive published daily means, 0 are fractional. Maximum pipeline rounding error is 0 ms (0%); selected jobs have maximum error 0 ms.

| Published daily mean | Function/day rows | Maximum added rounding error (ms) | Maximum relative error |
|---|---:|---:|---:|
| 0 < mean <= 1 ms | 3,594 | 0 | 0% |
| 1 < mean <= 4 ms | 7,020 | 0 | 0% |
| 4 < mean <= 10 ms | 11,990 | 0 | 0% |

There are 11,417 published zero means in retained duration observations. They remain unchanged and are ineligible for positive Process bursts; no 1-ms floor is invented for them. Integer published averages do not imply integer individual invocation durations or zero upstream quantization error. The unrounded means and original rounding convention are unavailable, so true submillisecond distortion cannot be quantified or recovered.

For hypothetical positive fractional means (not generated jobs), ceiling 0.1 ms to 1 ms adds 900%; 0.5→1 ms adds 100%; 1.2→2 ms adds 66.7%; 2.25→3 ms adds 33.3%. Relative ceiling error is unbounded as a true positive mean approaches zero. Daily averaging and using wall-clock time as CPU demand are much larger unresolved modeling assumptions than the measured conversion error in these published integer means.

## Controlled external evaluation assessment

**Suitable as a controlled, bounded external-trace-derived workload suite**, provided cohorts are reported separately and conclusions explicitly condition on reconstruction assumptions. It now contains sources from the high-volume tail, unchanged low/medium/quiet controls, mixed functions, 14 source days and all four six-hour blocks. Hour samples support comparisons at fixed observed temporal shape and reduced rate; snapshots support local-rate stress tests under the uniform-arrival assumption.

**Insufficient for population-level or production Azure scheduling claims.** Sampling fractions differ greatly; selected hours and functions are not a probability sample. Do not pool raw jobs or workloads as if they estimated invocation-weighted Azure performance. There are no measured CPU/I/O bursts, multicore state, dependencies, true individual latencies, actual subminute starts or cold-start timings. Full-traffic concurrency and true serverless execution are not reproduced. Overlapping source function/day/hour observations must be grouped to prevent leakage in any later split.

The prior synthetic comparison remains in reports/baseline/descriptive_statistics.json. Synthetic profiles use 8–12 jobs, uncalibrated ticks, repeated CPU/I/O phases and priorities 1–5. Refined Azure groups use explicit milliseconds, up to 2,000 jobs, one proxy burst, no I/O and priority 0. Existing short-job thresholds, quantums and model feature ranges therefore need a separately specified calibration phase. No scheduler or model was trained or evaluated here.
