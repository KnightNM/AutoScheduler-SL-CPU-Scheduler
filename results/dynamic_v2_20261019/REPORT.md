# Corrected dynamic ML pipeline: development audit

Status: **SYNTHETIC_DEVELOPMENT_ONLY. No candidate beats MLFQ.**

The policy-cost tree was selected on development workloads before evaluation.
Its evaluation score is 12.34% worse than the strongest eligible static
baseline, MLFQ, and its response tail is worse. Neither candidate passes the
original dynamic eligibility gates. No real-desktop model is selected or
approved by this experiment.

## Changes

- The realistic dynamic policy set is FCFS, RR quantum 2, Priority,
  Priority RR quantum 2/aging 8/switch cost 1, and MLFQ quanta `(2,4,8)`/aging 20.
  One deployable registry is shared with offline real replay labeling.
- The original six-policy simulation comparison is preserved. SJF/SRTF routing
  requires explicit `oracle_simulation` mode and remains an oracle experiment.
- `remaining_cpu_mean` and `remaining_cpu_variance` are removed. Fourteen
  ordered inputs use completed CPU bursts, accumulated observed service,
  queue sizes, waits, priorities, arrivals, I/O returns, and active policy/dwell
  state. Neither pending future jobs nor declared CPU/I/O work is read by the
  extractor. Completed bursts accumulate service across preemptions.
- Schema-v2 loading rejects legacy feature sets, five/six-policy mismatches,
  policy ordering/parameter changes, missing router configuration, runtime
  configuration drift, incompatible estimator input widths, and incompatible
  cost output counts. Historical saved models are preserved, not upgraded by
  changing their metadata.
- Development occupancy includes static policies, exploration, and a pilot
  classifier. Each behavior covers every development cohort size. Pilot
  rollout augmentation is restricted to training groups; held-out states use
  fixed behavior. The split manifest is written before fitting the pilot.
- Classifiers compare ordinary and balanced class weights. A small multi-output
  cost tree reuses the existing sklearn regressor factory and predicts one cost
  per eligible action. No additional ML framework is introduced.
- Tree settings and model family use realized whole-workload development
  scheduling score. Per-state regret, accuracy, confusion, and tie-aware
  accuracy are diagnostics. Exact label ties prefer keeping the active policy.
- Safe dispatch boundaries, startup RR, and minimum dwell are preserved.
  Classifiers require confidence 0.8. Cost models require predicted improvement
  of at least 0.005; their probabilities are unavailable and reported as null,
  rather than treating a deterministic prediction as confidence 1.
- Unused imports/local variables and the duplicated deployable replay registry
  are removed. Cumulative counters used by the historical benefit experiment
  remain. Algorithms, Azure processing, and historical experiment artifacts
  remain available.

## Protocol

The audit router configuration was fixed before fitting: epoch 10 ticks,
dwell 2 epochs, classifier confidence 0.8, cost margin 0.005. This audit does not
run the CLI's separate 27-configuration epoch/dwell/confidence tuning search.

Training uses 120 trace groups, seed 42, split into **84/18/18** complete
training/validation/test groups. There are 6,186 mixed-behavior decision rows
and 4,414 train-only pilot rollout rows, totaling 10,600. Cohort sizes are
3/6/12/18 per phase; only development generation changes.

Sixty independent seed-4242 workloads select tree settings, select the model
family, and freeze the strongest eligible static comparator. MLFQ wins with
score 0.192375. The final refitted classifier scores 0.220063 there; the cost
tree scores 0.215625, so the cost tree is frozen before evaluating seed 2026.

All **1,000 original seed-2026 workloads** retain their original generator,
cohort offsets, and process counts. Their seeds are disjoint from training and
validation. Both frozen candidates are audited; test performance never changes
the selection. Real locked-test data and gates are untouched.

Weighted score is lower-is-better using the unchanged synthetic score weights.
The six static simulation references fix normalization bounds for each
workload, including oracle references only as metric bounds. Adding Adaptive
cannot change those bounds. The historical model was replayed on this same
scale; archived candidate-dependent scores are not substituted.

## Before and after scheduling metrics

Values are means across workloads, except pooled decision P99. Response uses
simulator ticks. Starvation uses the existing report-only criterion, waiting
time greater than three times total CPU service, evaluated after completion.

| Metric | Historical six-policy model | Corrected classifier | Selected cost tree | Static MLFQ |
|---|---:|---:|---:|---:|
| Weighted score | 0.086652 | 0.220684 | 0.216191 | **0.192442** |
| Workload P95 response | 227.59005 | 51.51930 | 51.64850 | **35.85180** |
| Signed regret to best eligible static | -0.105791 | 0.028241 | 0.023749 | 0.000000 |
| Starvation count/workload | 32.012 | 32.320 | 32.287 | 32.307 |
| Accepted policy switches/workload | 1.942 | 0.000 | 3.614 | 0 |
| Pooled routing decision P99, ms | 0.4401 | 0.3899 | 0.3620 | not measured here |

The historical model uses hidden remaining CPU and SJF/SRTF oracle actions.
Its low weighted score is not a deployable baseline or a fair eligible model
comparison. Signed scheduling regret is against the best eligible static
policy on each workload, not an optimal sequence of dynamic switches; it can
be negative for a dynamic router. MLFQ is best on every evaluation workload.

The selected cost tree improves weighted score over RR/classifier by 2.04%,
but loses to MLFQ by **0.023749**, paired bootstrap 95% CI
**[0.022562, 0.024926]**. Its P95 response difference from MLFQ is
**+15.7967 ticks**, CI **[15.4774, 16.1235]**. The classifier never accepts a
switch under the frozen confidence threshold; its realized behavior equals RR.

Original gate rules are unchanged: Adaptive-minus-RR P95 CI upper bound must
be negative, score CI upper bound non-positive, and the largest per-workload
routing P99 strictly below 10 ms.

| Gate | Classifier | Cost tree |
|---|---|---|
| P95 response improvement over RR | fail: CI [0, 0] | fail: CI [+0.01365, +0.28151] |
| Weighted score non-regression to RR | pass: CI [0, 0] | pass: CI [-0.005415, -0.003564] |
| Original latency gate | pass: maximum workload P99 5.7630 ms | fail: maximum workload P99 26.2927 ms |
| Overall original eligibility | **false** | **false** |
| Beats frozen eligible comparator | **false** | **false** |

An independent replay after loader hardening reproduced all deterministic
scheduling metrics exactly. Its maximum workload P99 was 2.3544/3.6765 ms for
classifier/cost tree. This timing variation does not replace the initial
measurements or turn the first cost-tree latency failure into a pass.
The pooled P99 and maximum per-workload P99 are different statistics.

## Labels, classification, and regret

Development labels are imbalanced: FCFS 3,786; Priority 3,588; RR 2,625;
MLFQ 454; Priority RR 147. **34.76%** of rows have exact optimal-action ties,
including dwell-blocked states whose feasible outcomes coincide.

| Held-out grouped decision-row diagnostic | Classifier | Cost tree |
|---|---:|---:|
| Test accuracy | 41.79% | 12.63% |
| Tie-aware test accuracy | 44.47% | 42.57% |
| Validation action regret | 0.147318 | 0.100757 |
| Test action regret | 0.121672 | 0.113986 |
| Depth / minimum leaf samples | 5 / 1 | 5 / 10 |
| Class weighting | balanced | not applicable |

These diagnostics evaluate the train-only chosen tree, before the saved
train+validation refit. They are not on-kernel accuracy or direct comparisons
with historical accuracies. Historical five-policy and six-policy reports
record 47.51% and 84.33% test accuracy respectively, but use different labels
and do not document the corrected grouped protocol. Their regret values are
not leakage-corrected evidence.

Confusion matrices below use rows = chosen minimum-cost label, columns =
predicted action. Exact ties explain part of the cost model's low strict
accuracy; they do not explain away its worse realized scheduling performance.

| Classifier | FCFS | RR | Priority | Priority RR | MLFQ |
|---|---:|---:|---:|---:|---:|
| FCFS | 27 | 116 | 114 | 0 | 55 |
| RR | 7 | 155 | 52 | 0 | 20 |
| Priority | 13 | 114 | 112 | 0 | 23 |
| Priority RR | 0 | 0 | 0 | 19 | 0 |
| MLFQ | 5 | 1 | 1 | 0 | 61 |

| Cost tree | FCFS | RR | Priority | Priority RR | MLFQ |
|---|---:|---:|---:|---:|---:|
| FCFS | 11 | 12 | 101 | 0 | 188 |
| RR | 39 | 9 | 27 | 0 | 159 |
| Priority | 15 | 14 | 61 | 0 | 172 |
| Priority RR | 19 | 0 | 0 | 0 | 0 |
| MLFQ | 26 | 0 | 10 | 0 | 32 |

## Reproduction and artifacts

Python 3.12.3; scikit-learn 1.9.1. Versioned candidate models and generated
training data stay under ignored `artifacts/dynamic_v2_20261019/candidates/`.
Reports, split-group identifiers, hashes, configurations, and workload-level
summaries are retained here. No private raw/processed desktop traces are added.

To reproduce into fresh paths from the repository root:

```bash
.venv/bin/python tools/capture_historical_dynamic.py \
  --revision 3e01e947ba72e111da44317706014fb3f1c01075 \
  --model results/six_policy/dynamic_model.joblib \
  --output artifacts/dynamic_v2_reproduction/before.json
.venv/bin/python -m autoscheduler.dynamic_research \
  --output results/dynamic_v2_reproduction \
  --artifacts artifacts/dynamic_v2_reproduction/candidates \
  --before artifacts/dynamic_v2_reproduction/before.json
.venv/bin/python -m unittest discover -s tests -v
```

The historical helper explicitly executes the selected local historical
dynamic module and loads its local saved model for audit only. The active
loader's compatibility checks are never weakened. Its scheduling outputs were
checked against the original before capture.

`protocol.json` records pre-fit source hashes; `frozen_selection.json` records
selection before evaluation; `research_summary.json` contains complete metrics
and checksums; `classifier_training.json` and `policy_cost_training.json`
contain grids, importances, splits, and confusion; each family directory holds
workload-level scores and diagnostics. `verification.json` records identical
scheduling results after dimensional validation and final source hashes.
Post-protocol changes only harden estimator validation and mark unavailable
cost confidence as null; they do not alter scheduling decisions.

## Limits and validation

Next-epoch counterfactual labels still use synthetic future outcomes as
offline targets, then continue with RR. Labels act until the next safe dispatch
boundary at or beyond the epoch; they do not interrupt a non-preemptive burst.
This is an approximation to the long-term adaptive objective, not a model of
real Linux policy switching. State coverage includes one pilot rollout pass,
not a guarantee of coverage under every learned controller. Tree probabilities
are uncalibrated; the cost tree has a margin, not an uncertainty estimator.

The audit uses the existing synthetic weighted objective and reports process
response. It does not substitute for the frozen desktop objective, foreground
wakeup measurement, application-group split, or locked real-trace gates.
Existing real pilot reports remain insufficient-data development evidence.
The new pipeline does not fix the limited causal scope of those pilot replay
labels and does not train a final real model from them.

Regression checks cover hidden-future perturbations, completed burst service,
MLFQ parity, oracle isolation, grouping, pilot occupancy, dwell/confidence,
dispatch boundaries, corrupted bundles, and cost-report serialization.
Independent randomized dispatcher parity passed 700 policy/workload cases.
All 182 regression tests pass; real-config and collection/isolated Firefox
dry runs pass. Graphify was updated with AST-only extraction; its community
names may need a separate semantic refresh after the structural update.

**Recommendation from this audit: retain static MLFQ as the eligible comparator.
Do not promote either learned candidate or begin sched_ext work.**
