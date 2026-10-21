# Dynamic ML v6: final synthetic checkpoint

**Do not promote v6. Preserve v5 as the research candidate and static MLFQ
`(1,2,4)`, aging 40, as the simulator recommendation. Synthetic tuning is closed.**
No real-Linux performance or deployment approval is established. The next
development phase is the interactive dashboard; no frontend is implemented here.

## Change and protocol

One production change adds configurable `arrival_quiet_dwell_periods` to the
existing observed-state admission guard. Default 1 preserves v5 and historical
behavior; this experiment uses 2 (40 quiet ticks). Runtime, occupancy generation,
and feasible counterfactual labels share the existing guard. Minimum dwell 20,
safe dispatch boundaries, first-service protection, no-switch, confidence 0.8,
cost margin, finite excursion, and MLFQ fallback are retained. All 19 inputs and
their schema remain unchanged and observed-only. Loading a model with different
controller configuration is rejected. No algorithm or objective weight changes.

`DIAGNOSIS.md` identifies the three responsible Priority departures. Old v5
workloads are used only for diagnosis. The protocol is written before fitting:
144 new training traces (seed 10601), 84 scheduling-validation traces (10602),
and one 240-workload audit (10603), 40 per family, with no outcome filtering.
Complete trace groups split 100/22/22; a train-only pilot adds on-policy states.
The unchanged nine-setting static grid and six classifier/three cost-tree grid
are selected only on development validation. Saved models retain their evaluated
train-only fit; there is no post-audit fitting or candidate reselection. Frozen
1,000-workload and real traces are not consulted.

**Design limitation:** independently rerunning the static grid selected MLFQ
`(2,4,8)`, aging 40, for v6, versus v5's `(1,2,4)`, aging 40. Validation scores
were 0.181689 and 0.183934 respectively. Consequently, the main v6/v5 comparison
tests a combined refit/controller/static-parameter change and cannot isolate the
guard. This matters substantially for response. A fixed-parameter sensitivity
check and guard-only intervention explain the confounding; neither is used to
select a replacement model or reinterpret the prespecified audit gates.

## Fresh audit: comparable inputs, 240 workloads

Scores are dimensionless, lower is better. P95 is the mean of workload-level
first-response P95s in simulator ticks, not a pooled process percentile.
Worst is the maximum first response across all jobs. Starvation uses the frozen
fairness definition, averaged per workload. Switches are accepted transitions
per workload. P99 is pooled controller decision latency in milliseconds;
the actual latency gate uses the maximum workload P99.

| Controller | Score | Mean P95 | Worst | Starvation | Switches | Decision P99 ms |
|---|---:|---:|---:|---:|---:|---:|
| Original v5 cost, replayed | 0.144594 | 5.77208 | 47 | 9.55833 | 2.92917 | 0.50713 |
| V6 classifier, diagnostic | 0.176913 | 12.36521 | 94 | 9.87917 | 1.72083 | 0.49162 |
| V6 cost, development-selected | 0.166880 | 12.36521 | 94 | 9.71667 | 1.90833 | 0.42325 |
| V6 development-selected static `(2,4,8)/40` | 0.182573 | 12.36521 | 94 | 9.87500 | 0 | unmeasured |
| Default static MLFQ `(2,4,8)/20` | 0.186227 | 13.62542 | 94 | 10.01667 | 0 | unmeasured |
| Previous frozen static `(1,2,4)/40` | 0.178557 | 5.71437 | 47 | 9.87917 | 0 | unmeasured |
| V5 plus v6 guard, explanatory ablation | 0.158840 | 5.71437 | 47 | 9.64167 | 2.70000 | 0.45223 |

Original v5's previously reported 0.13589 / 7.645 and static 0.16756 / 7.48729
belong to a different workload sample. They are preserved and are not treated
as paired before/after observations here. All five eligible static policies and
both new candidates are included in `audit/workloads.csv` and `audit/summary.json`.

Paired workload bootstrap 95% intervals use 10,000 resamples and seed 2027:

| Difference, first minus second | Mean score difference [95% CI] | Mean P95 difference [95% CI] |
|---|---|---|
| V6 cost − new selected static | −0.015693 [−0.022550, −0.009576] | 0 [0, 0] |
| V6 cost − v5 | +0.022286 [+0.013376, +0.031331] | +6.593125 [+5.168708, +8.087766] |
| V6 cost − previous frozen static | −0.011678 [−0.019305, −0.004522] | +6.650833 [+5.257870, +8.129177] |
| Guard-only − v5 | +0.014246 [+0.008009, +0.020926] | −0.057708 [−0.173125, 0] |

The isolated guard reduces mean P95 by 0.05771 ticks (about 1%) and matches the
previous static baseline on every workload's P95. Its score cost is statistically
clear; the P95 improvement interval includes zero. This is a modest response
tradeoff, not a demonstrated overall improvement over v5. New v6's apparent
response safety against its own selected static does not imply preservation of
the previous static response envelope.

V6 cost starvation difference against its selected static is −0.15833
[−0.22500, −0.09583]. Maximum workload decision P99 is 0.96624 ms, below the
unchanged strict 10 ms gate; v5 is 2.71121 ms and guard-only 3.24412 ms. These
host-dependent simulator routing timings exclude real-kernel/controller overhead.
All score, response, worst-response, starvation and switching intervals, including
exploratory family intervals, are in the machine-readable audit and sensitivity.

## Workload families (40 each)

| Family | V5 score / P95 | V6 cost score / P95 | Frozen prior static score / P95 | Guard-only score / P95 |
|---|---:|---:|---:|---:|
| Cohort mix | .05149 / 4.500 | .06300 / 9.638 | .04990 / 4.500 | .05037 / 4.500 |
| Homogeneous batch | .11265 / 14.583 | .22889 / 29.165 | .29104 / 14.583 | .18047 / 14.583 |
| Long I/O | .28919 / 13.198 | .28797 / 29.134 | .30486 / 13.198 | .30023 / 13.198 |
| Low load | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| Repeated changes | .15093 / 1.384 | .15800 / 3.409 | .16148 / 1.384 | .15791 / 1.384 |
| Sustained arrivals | .26330 / .969 | .26341 / 2.846 | .26405 / .622 | .26405 / .622 |

The guard-only response benefit occurs entirely in sustained arrivals; other
families' P95s are unchanged. Guard-only batch score worsens most (+0.06783),
because delayed departures sacrifice beneficial switching time. The new v6
model has worse P95 in every non-low-load family versus v5; batch and long-I/O
regressions are consistent with larger initial MLFQ quanta. V6 long-I/O score
slightly improves but its paired score interval includes zero. Family comparisons
are explanatory and not multiplicity-corrected selection tests.

## Training and gates

There are 7,080 labeled rows: 3,501 mixed-state and 3,579 train-only pilot rows.
Labels are No Switch 4,108; FCFS 1,426; Priority 1,403; RR 124; Priority-RR 19.
This remains imbalanced with many equivalent actions. Grouped validation strict
accuracy is 87.87% for the depth-8 classifier and 5.12% for the depth-5 cost tree;
action regret is .001156 and .000903. Internal held-out development-group
tie-aware accuracy is 84.96% / 86.72%. These are label diagnostics, not scheduling
acceptance. Full confusion matrices/candidate diagnostics are in training JSONs.

The classifier fails starvation on validation and audit and remains diagnostic.
The cost tree passes all six **prespecified** validation and audit gates against
the independently development-selected static: score CI, P95 CI, starvation,
latency, and the original RR score/response requirements. Selection is frozen
before auditing. The supplemental previous-frozen-static check fails P95 for v6;
v5 also retains a small response failure against that baseline. These checks are
reported separately rather than retrospectively changing acceptance thresholds.
No candidate establishes the locked real-trace gates, and synthetic data cannot
select the final real-data model under `AGENTS.md`.

V6 therefore does **not** demonstrate the requested improvement over v5 while
preserving the established response envelope. No promotion occurs. The guard
remains configurable and opt-in; v5/default behavior stays at one quiet interval.
The post-audit guard-only intervention is not eligible for post-hoc promotion.

## Integration and reproducibility

`configs/research_status.json` is the read-only, schema-versioned integration
manifest. It lists five observable-policy algorithms, oracle references, v2–v6
artifact availability/checksums and historical/experimental status, no approved
ML models, static recommendation, dataset-scoped metrics/units, actual gates,
and report paths. Missing timings are null. It includes the separately labeled
fixed-baseline sensitivity; numerical claims are sourced from JSON reports.
Regenerate with `.venv/bin/python -m autoscheduler.research_status`.

Reproduce in fresh versioned paths by copying the preserved v5 `before_source`
snapshot and running `python -m autoscheduler.dynamic_v6_experiment --output ...
--artifacts ...`. Existing experiment paths refuse overwrite. The archived-source
v5 replay and checksummed protocol retain provenance. The fixed sensitivity tool
is `python -m autoscheduler.dynamic_v6_sensitivity`; it never fits/selects models.

`verification.json` records regression tests, exact MLFQ control matches, grouped
split/seed disjointness, source/model checksums, historical preservation, graph
update, and frozen real-config validation. Azure and real-Linux sources and
configurations are unchanged. No dashboard/backend implementation is included.

**Stop synthetic ML tuning here.** Retain the response-first static simulator
baseline and expose the measured limitations honestly in the future dashboard.
