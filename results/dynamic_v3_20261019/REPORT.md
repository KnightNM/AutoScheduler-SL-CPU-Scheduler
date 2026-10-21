# Dynamic ML corrective experiment

**SYNTHETIC_DEVELOPMENT_ONLY. Corrections implemented; neither model accepted or promoted.**
The development-selected classifier improves on the previous selected model,
but loses to continuous default MLFQ on the 1,000 original workloads. Both
candidates lose substantially to development-tuned MLFQ there. New development
workloads expose weighted-score opportunities alongside unacceptable response
tails. This is evidence of useful simulation headroom, not a successful controller.

## Exact corrections

- `simulator/engine.py` and `autoscheduler/dynamic.py` separate original ready
  enqueue time from `aging_since`. Promotions reset only aging; ready-wait
  features and post-I/O wait retain elapsed queue time. A deterministic example
  previously reported one tick instead of 21 ticks of ready wait.
- Static MLFQ reselects after paying nonzero dispatch overhead, including
  arrivals, I/O returns, and aging observed by its end. It charges overhead
  once and avoids the old zero-service dispatch. The minimal regression's
  late arrival runs at tick 5 instead of allowing demoted work to run first.
  A paid dispatch attempt can end by resuming the preceding PID if it wakes
  during overhead; charged CS intervals and actual PID transitions are distinct.
- Action labels exclude dwell-blocked states. They hold each candidate through
  minimum dwell, then to the next global review and safe dispatch boundary,
  before continuing with MLFQ. An idle jump checks the review deadline before
  dispatching a late job. This additional defect was reproduced and fixed.
- Label costs share six full-workload static reference bounds and subtract
  immediate MLFQ continuation from the same observed prefix. MLFQ's relative
  action cost is zero. Targets may use synthetic future outcomes; inputs cannot.
- Startup and fallback are configured independently. API/CLI defaults preserve
  RR startup and hold-current fallback. This experiment explicitly uses MLFQ
  startup and MLFQ low-confidence/unavailable-model fallback. Fallback observes
  dwell and dispatch constraints; incompatible models still raise errors.
- Fourteen observed inputs remain: completed-burst statistics, accumulated CPU
  service, current queues/priorities/waits, arrivals and I/O returns already
  observed, active policy, and remaining dwell. No declared CPU/I/O totals,
  future arrivals, true remaining burst, final outcomes, or oracle identities
  are inputs. Schema 3 rejects saved schema-2 models rather than reinterpreting
  corrected feature semantics. Historical models and archived source remain intact.
- `development_workloads.py` adds six deterministic development families:
  mixed cohorts, sustained arrivals, low load, long I/O, repeated changes, and
  homogeneous batch. Family and behavior are crossed independently. The
  original evaluation generator remains unchanged.
- `dynamic_v3_experiment.py` records protocol, groups, static tuning, model
  selection, paired audits, and gates. Classifier/cost trees reuse sklearn;
  hyperparameters and family use realized validation schedules. Accuracy is
  diagnostic. Dynamic action-cost means are labeled as action costs, not static
  scheduler performance. CLI outputs move to schema-3 paths; the historical
  router search remains available explicitly with `--tune-router`.

## Frozen protocol and validation

144 development training traces, seed 7301, split into **100/22/22 whole trace
groups**. The manifest precedes pilot fitting. There are 5,972 mixed-behavior
rows and 4,415 train-only pilot rows: **10,387** total. No group crosses splits.
Sixty independent seed-7302 development workloads choose tree settings and
model family. An additional 120 seed-7303 development workloads, 20 per family,
are audited after selection. The original 1,000 seed-2026 workloads are unchanged.
They were examined in earlier diagnostics, so they are a regression audit,
not a newly unseen confirmatory test. No real locked-test data is accessed.

Router: epoch 10, dwell two epochs, classifier confidence 0.8, cost advantage
margin 0.005, MLFQ startup/fallback, MLFQ continuation. Static MLFQ tuning uses
only development validation: quanta `(1,2,4)/(2,4,8)/(4,8,16)` crossed with
aging `10/20/40`, switch cost zero. The selected parameters are **`(1,2,4)`,
aging 40**. This sensitivity grid was informed by the earlier diagnostic;
it is not evidence from a pristine external benchmark. The deployable registry
and real research contract retain their original parameters.

Validation scores: classifier **0.120536**, cost tree **0.128198**, default MLFQ
0.162973, tuned MLFQ 0.145549. The **classifier** is frozen before auditing;
the cost tree is not substituted after seeing its better development-audit score.
Classifier: unrestricted depth/minimum leaf 5, ordinary class weights.
Cost tree: depth 8/minimum leaf 10. The saved models refit internal training
plus validation; decision-row test diagnostics evaluate the train-only trees.

Weights remain waiting .30, response .25, turnaround .20, utilization .15,
throughput .10. Candidate-independent normalization retains the original six
static references; SJF/SRTF are oracle bounds only. Five eligible policies are
FCFS, RR2, Priority, Priority-RR `(2,8,1)`, and MLFQ. No score, gate, frozen
workload, Azure dataset, or real-data configuration is altered.

## Original 1,000-workload comparison

Lower score, response, starvation, and regret are better. Values are means per
workload; P95 is each workload's process first-response P95 in simulator ticks.
Starvation retains the historical report-only rule: waiting exceeds three times
total CPU service. It is not an input or an independent new acceptance threshold.

| Scheduler | Score | P95 response | Starvation | Switches/workload |
|---|---:|---:|---:|---:|
| Before: schema-2 classifier | 0.220684 | 51.51930 | 32.320 | 0 |
| Before: selected schema-2 cost tree | 0.216191 | 51.64850 | 32.287 | 3.614 |
| After: selected classifier | 0.196213 | 42.78145 | 32.196 | 6.690 |
| After: cost tree | 0.196170 | 37.46335 | 32.295 | 2.533 |
| Continuous default MLFQ | **0.192442** | **35.85180** | 32.307 | 0 |
| Development-tuned static MLFQ | **0.146381** | **4.53920** | 32.131 | 0 |
| FCFS | 0.390824 | 246.81355 | 30.755 | 0 |
| RR2 | 0.220684 | 51.51930 | 32.320 | 0 |
| Priority | 0.405997 | 446.31730 | 28.325 | 0 |
| Priority-RR | 0.775096 | 81.62845 | 32.270 | 0 |

Selected-after minus selected-before score is **−0.019978**, paired 95% CI
**[−0.021299, −0.018665]**, a 9.24% mean improvement. Response changes by
**−8.86705 [−9.79076, −7.90744]** ticks, starvation by
**−0.091 [−0.119, −0.063]**, switches by **+3.076 [2.90698, 3.24602]**.
These reflect the combined corrections, changed development distribution, and
new fit; this experiment does not isolate each correction's contribution.

Paired candidate-minus-baseline differences, 10,000 workload bootstrap samples,
seed 2027, percentile 95% intervals:

| Candidate / baseline | Score difference [CI] | P95 difference [CI] | Starvation difference [CI] | Score wins/ties/losses |
|---|---|---|---|---|
| Classifier / default MLFQ | +0.003771 [0.002840, 0.004742] | +6.92965 [6.04876, 7.82822] | −0.111 [−0.134, −0.090] | 428/8/564 |
| Cost / default MLFQ | +0.003728 [0.003329, 0.004136] | +1.61155 [0.95920, 2.35061] | −0.012 [−0.020, −0.005] | 261/13/726 |
| Classifier / tuned MLFQ | +0.049832 [0.048526, 0.051176] | +38.24225 [37.33494, 39.17430] | +0.065 [0.024, 0.106] | 17/0/983 |
| Cost / tuned MLFQ | +0.049789 [0.048926, 0.050650] | +32.92415 [32.24279, 33.67293] | +0.164 [0.131, 0.199] | 2/0/998 |

Signed scheduling regret to the best eligible static policy **including the
development-tuned comparator** is 0.049832/0.049789 for classifier/cost. Under
the original five-action registry it is 0.003771/0.003728. These are distinct
from decision-row counterfactual action regret and from an optimal switching oracle.

## Separate development audit

| Scheduler | Score | P95 response | Starvation | Switches |
|---|---:|---:|---:|---:|
| Default MLFQ | 0.155625 | 19.32500 | 15.792 | 0 |
| Tuned MLFQ | 0.138661 | 7.70667 | 15.283 | 0 |
| Selected classifier | 0.138091 | 35.75833 | 15.467 | 6.250 |
| Cost tree | 0.120779 | 69.91792 | 14.600 | 1.167 |

Classifier-minus-tuned score CI **[−0.016499, +0.017109]** includes zero;
P95 worsens **28.05167 [21.40320, 36.82361]** ticks. The unselected cost tree
does beat tuned MLFQ on score: **−0.017881 [−0.029948, −0.005960]**,
but P95 worsens **62.21125 [45.22526, 81.12857]** ticks. It fails acceptance.
Its negative signed regret to best static, −0.013276, demonstrates switching
headroom rather than a deployable improvement.

| Family (20 cases each) | Default MLFQ score | Tuned MLFQ | Classifier | Cost |
|---|---:|---:|---:|---:|
| Mixed cohorts | 0.107864 | 0.063866 | 0.183097 | 0.111173 |
| Sustained arrivals | 0.177902 | 0.172215 | 0.189957 | 0.177252 |
| Low load | 0 | 0 | 0 | 0 |
| Long I/O | 0.212179 | 0.197310 | 0.170534 | 0.171412 |
| Repeated changes | 0.195758 | 0.196801 | 0.165661 | 0.184685 |
| Homogeneous batch | 0.240049 | 0.201772 | 0.119299 | 0.080153 |

The controls distinguish useful late/batch changes from sustained-arrival
regressions. Low-load ties do not establish an adaptive advantage. Full static
comparisons and family response/starvation are in `development_audit/summary.json`.

## Classification, latency, and failed gates

Grouped decision-row accuracy is **40.81%/46.62%** for classifier/cost;
tie-aware accuracy **44.37%/58.24%**, action regret **0.006111/0.003887**.
These labels differ from schema 2 and do not support a direct accuracy claim.
27.51% of rows have exact optimal-action ties. Labels remain imbalanced:
FCFS 3,835, Priority 3,307, MLFQ 2,419, RR 800, Priority-RR 26.
Both training reports contain complete confusion matrices and candidate grids.
Dwell is constant zero on actionable states and has no importance; the previous
spurious dependence on dwell is removed. More switching is not proof of benefit.

| Routing measurement, ms | Classifier | Cost |
|---|---:|---:|
| Historical schema-2 pooled P99 | 0.3899 | 0.3620 |
| Historical maximum workload P99 | 5.7630 | 26.2927 |
| New development-audit pooled P99 | 0.3713 | 0.3628 |
| New original-workload first-audit pooled P99 | 0.5419 | 0.4974 |
| New first-audit maximum workload P99 | 9.8189 | **11.8740** |
| Original-gate recording pooled P99 | 0.6412 | 0.6205 |
| Original-gate maximum workload P99 | **11.3961** | 6.4151 |

Timing includes feature extraction, prediction, safeguards, and accepted queue
rebuild. The two audit passes have identical deterministic schedules but noisy
wall-clock timings. The first cost-tree violation is retained; the later pass
does not erase it. Both candidates have a recorded strict `<10 ms` failure.
These Python simulator timings are not end-to-end Linux controller evidence.

Original unchanged RR-relative response and score gates pass for both new
candidates. In the original-gate recording, classifier latency fails and cost
latency passes, so that recording reports eligibility false/true respectively.
**Both fail** score, P95, and mean-starvation non-regression against the stronger
development-selected static comparator, tuned MLFQ. Both also fail the
conservative all-recorded-passes latency check. Real locked-trace gates remain
unestablished. No registry update, model promotion, frontend, or sched_ext work occurs.

## Verification, limits, and next step

**222 tests pass**, including deterministic regressions for every correction,
hidden-future perturbations, schema rejection, group isolation, safe review/dwell,
fallback, idle gaps, paired comparison, and workload preservation. Independent
checks cover 3,000 MLFQ accounting cases at costs 0/1/3 and 60 training/runtime
feature-sequence comparisons. Archived versus corrected default MLFQ has
identical inputs, timelines, and process metrics on all 1,000 original workloads.
All 53 protected artifact/configuration checksums and pre-fit source hashes match.
`real-config`, demo smoke, whitespace check, and AST-only graph update pass.

The implementation defects are fixed; the remaining failures are controller
and objective limitations. Scalar weighted score rewards mean behavior while
acceptance also requires response-tail and starvation safeguards. A finite
action plus MLFQ tail approximates repeated learned decisions. One pilot pass
does not guarantee on-policy coverage. Classifier probabilities are uncalibrated;
cost margin is not uncertainty. Switching into MLFQ resets feedback as before,
and the frozen simulation assigns zero overhead to most policies. Development
counts are 12/24/36; real workloads, smaller long-I/O populations, heterogeneous
mixes, and kernel overhead remain unvalidated. One training seed is used; CIs
describe workload sampling conditional on these fitted models, not training
variability. Historical test reuse and numerous exploratory comparisons limit
confirmatory claims.

Before another experiment, keep MLFQ as the control and add the **existing**
tail/starvation acceptance constraints to development candidate selection rather
than ranking only scalar score. Test an observed first-service-coverage guard
before leaving MLFQ, with ready jobs awaiting first dispatch and observed wait
quantiles as inputs; this targets the demonstrated response failure without
using future work. Validate it with deterministic arrival/I/O controls before
fitting. Assess feedback-reset and switching overhead sensitivity separately;
do not alter frozen costs or weights. Pre-register fresh grouped captures for
real validation; synthetic results cannot choose the final real-data model.

Models/data remain local under ignored `artifacts/dynamic_v3_20261019/`.
`protocol.json`, `static_tuning.json`, and `frozen_selection.json` record decisions
before auditing. `research_summary.json`, both training reports, workload CSVs,
`before_after_paired.json`, and verification JSONs retain complete evidence.
Reproduce into **fresh** paths:

```bash
.venv/bin/python -m autoscheduler.dynamic_v3_experiment \
  --output results/dynamic_v3_reproduction --artifacts artifacts/dynamic_v3_reproduction
.venv/bin/python -m unittest discover -s tests -v
```
