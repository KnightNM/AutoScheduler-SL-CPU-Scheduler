# One focused Dynamic ML development experiment

**SYNTHETIC_DEVELOPMENT_ONLY. Neither candidate passes every gate. No promotion.**
The selected cost tree improves weighted score and starvation over tuned static
MLFQ, but regresses on response tails. Retain tuned static MLFQ as the recommended
synthetic baseline. No further tuning or Random Forest experiment was run.

## Changes and protocol

- The active router blocks departures from MLFQ while any currently ready job
  has no observed CPU service. It allows departures after first allocation;
  dwell, safe dispatch boundaries, confidence, cost margin, and MLFQ fallback remain.
- Eighteen observed inputs include first-service queue count/max wait, ready-wait
  median/P95, existing queue lengths and recent arrivals, and execution history.
  Neither pending future jobs nor declared remaining work influences these inputs.
- An explicit `No Switch` action holds the current policy. The cost tree predicts
  signed relative costs; their negatives are expected benefits versus immediate
  MLFQ continuation. Targets respect the guard, dwell, global review grid, safe
  dispatch, and idle boundaries, then continue with MLFQ. No-switch wins label ties.
  Actual scheduler policies remain five; the six model actions include no-switch.
- Candidate selection first ranks safety eligibility, then realized scheduling
  score, action regret, and simpler trees. Accuracy is diagnostic. Saved models
  retain the evaluated train-only fit; there is no unchecked refit afterward.
- Schema 4 rejects v3 models in the active loader. An isolated archived v3
  implementation/model supplies the before control, without metadata modification.
- Development-only families are balanced: mixed cohorts, unpredictable sustained
  arrivals, low load, long I/O, homogeneous batch, repeated changes. Counts are
  sampled from 3/6/12/24/48. Prespecified sparse long-I/O controls expose non-MLFQ
  winners; no traces are retained or rejected according to their outcome.

72 training traces, seed **8401**, split into **50/11/11** complete trace groups.
The manifest precedes pilot fitting; pilot augmentation is train-only.
There are **1,626 mixed + 1,248 pilot = 2,874** decision rows. Thirty-six independent
seed-8402 development workloads choose settings. The search has **six classifier
trees** (depth 3/5/8, ordinary/balanced weights, leaf 10) and **three cost trees**
(depth 3/5/8, leaf 10). Every candidate fails at least one development gate;
the cost tree is frozen as the best-score **diagnostic candidate**, not an accepted model.
The only subsequent audit has **120 fresh seed-8403 workloads**, 20 per family.

The same nine-configuration static MLFQ grid as v3 is selected on development
validation only. It chooses **quanta `(1,2,4)`, aging 40**, the strongest static
comparator: validation score **0.175348**, versus default MLFQ 0.187322.
Experimental router MLFQ uses these same parameters so the comparison does not
penalize it for default startup quanta. A protected no-model control exactly
matches tuned static MLFQ on all 120 audit workloads. Parameter gains are not ML gains.
Production registry defaults and the real-Linux research configuration are unchanged.

Weights, six-reference normalization, confidence 0.8, dwell 20 ticks, epoch 10,
cost margin 0.005, and strict maximum-workload routing P99 `<10 ms` remain unchanged.
Primary score requires paired CI upper bound `<0`; P95 upper bound `<=0`;
mean starvation cannot increase. Original RR-relative gates are also retained.
SJF/SRTF supply oracle metric bounds only. The previously examined 1,000-workload
audit and locked real-data tests are **not replayed or used for tuning**.

## Fair before/after: the same fresh 120 workloads

Lower is better. Response is mean workload process first-response P95, in simulator
ticks. Starvation retains the existing waiting-time-greater-than-three-times-CPU
criterion. Timing measures the complete routing decision, not Linux controller latency.

| Scheduler | Score | P95 response | Starvation | Switches/workload | Pooled routing P99, ms | Maximum workload P99, ms |
|---|---:|---:|---:|---:|---:|---:|
| Previous selected v3 classifier | 0.151634 | 24.10583 | 11.225 | 4.358 | 0.4387 | 2.2046 |
| New classifier | 0.181499 | 7.13583 | 11.333 | 0.333 | 0.4666 | 0.8424 |
| New selected cost tree | **0.121676** | 15.10833 | **10.817** | 4.383 | 0.3943 | 0.5010 |
| Default static MLFQ | 0.168516 | 15.59708 | 11.708 | 0 | — | — |
| Tuned static MLFQ | 0.158909 | **6.63917** | 11.292 | 0 | — | — |
| Protected tuned-MLFQ no-model control | 0.158909 | 6.63917 | 11.292 | 0 | 0.2897 | 0.3527 |
| FCFS | 0.302920 | 155.12542 | 11.108 | 0 | — | — |
| RR2 | 0.212824 | 19.24208 | 12.300 | 0 | — | — |
| Priority | 0.294749 | 225.93958 | 10.008 | 0 | — | — |
| Priority-RR | 0.845031 | 36.80083 | 13.375 | 0 | — | — |

The historical 1,000-workload numbers **0.19621/0.14638** are context only;
they must not be compared numerically with this new audit's different distribution.
On the same fresh inputs, new cost-tree score improves **19.76% over v3** and
**23.43% over tuned MLFQ**. The classifier regresses on score. Static dispatch-only
timings were not measured; the no-model control includes the same feature/guard overhead.

Paired 95% percentile workload bootstrap CIs, 10,000 resamples, seed 2027:

| Difference | Score [CI] | P95 response [CI] | Starvation [CI] |
|---|---|---|---|
| Cost minus tuned MLFQ | −0.037234 [−0.060965, −0.011452] | **+8.46917 [5.17743, 12.28933]** | −0.475 [−0.775, −0.183] |
| Classifier minus tuned MLFQ | +0.022589 [0.004828, 0.048767] | +0.49667 [0.09792, 1.02044] | +0.04167 [−0.00833, 0.10833] |
| Cost minus previous v3 | −0.029958 [−0.051247, −0.008042] | −8.99750 [−13.95630, −4.10742] | −0.40833 [−0.70833, −0.10833] |

Cost-tree switching changes by **+0.025 [−0.875, 1.05833]** versus v3; no reduction
is established. Its signed regret to each workload's best static is −0.013513,
showing switching headroom, not safety eligibility.

## Family results and failed gates

| Family, 20 cases each | Tuned MLFQ score / P95 | Cost score / P95 | Classifier score / P95 |
|---|---|---|---|
| Mixed cohorts | 0.06827 / 4.6025 | 0.08432 / 8.4175 | 0.17687 / 6.3650 |
| Sustained arrivals | 0.19751 / 0.6200 | 0.25370 / 17.3125 | 0.22387 / 1.8375 |
| Low load | 0 / 0 | 0 / 0 | 0 / 0 |
| Long I/O | 0.29113 / 13.0475 | **0.20205 / 13.0475** | 0.29113 / 13.0475 |
| Repeated changes | 0.14807 / 1.9950 | 0.14363 / **32.3025** | 0.15036 / 1.9950 |
| Homogeneous batch | 0.24848 / 19.5700 | **0.04636 / 19.5700** | 0.24676 / 19.5700 |

Batch and long-I/O score gains preserve first-response P95. Their mean starvation
also improves: 21.30→19.15 and 15.60→14.45 respectively. Repeated changes and
sustained arrivals dominate the remaining response failures. Other static policies
genuinely beat default MLFQ in 20 FCFS, 17 RR, 16 Priority, and one Priority-RR
audit workloads; these counts overlap and were not used to select inputs.

| Acceptance gate | Classifier | Cost |
|---|---|---|
| Primary score improvement | fail | pass |
| Primary P95 non-regression | **fail** | **fail** |
| Primary mean starvation non-regression | fail | pass |
| Routing latency | pass | pass |
| Original RR-relative score | pass | pass |
| Original RR-relative P95 improvement | pass | fail |
| Development-validation eligibility | fail | fail |
| Accepted / promoted | **no / no** | **no / no** |

## Training diagnostics, validation, and limits

Selected classifier: depth 8, balanced weights, leaf 10; cost: depth 8, leaf 10.
Validation scores are **0.174888/0.133137**, but neither is safe. Grouped decision-row
test accuracy is **28.24%/27.74%**, tie-aware accuracy **32.32%/69.47%**, action regret
**0.010538/0.002138**. Labels: No Switch 1,021; FCFS 821; Priority 653; RR 200;
MLFQ 164; Priority-RR 15. Exact ties affect 46.83% of rows, partly because MLFQ
and No Switch coincide while active MLFQ. Full confusion matrices and all nine
candidate validation metrics are retained in the training reports.

**231 regression tests pass**, including guard release, explicit no-switch,
six-action bundle persistence, observed-only perturbations, configured/static
MLFQ parity, safety-first selection, and deterministic workload diversity.
All **122 protected artifact/configuration hashes** and pre-fit source hashes
match. Real-config, whitespace checks, and AST graph update pass. No frontend,
Azure dataset, score weight, historical result, or real research configuration changed.

The guard protects departures, but does not force re-entry when new unserved
jobs appear under another policy. A retrospective witness, seed **8403000040**,
leaves for FCFS at tick 231 with zero unserved ready jobs. P26 arrives at 245,
starts at 399, and waits 154 ticks; the model keeps FCFS until tick 394.
Cost-tree workload P95 is 152.65 versus tuned MLFQ's 6.0. The departure guard
worked; repeated no-switch decisions did not protect subsequent arrivals.
`tail_diagnostic.json` retains the witness without replacing audit timing.
Dwell and safe dispatch also constrain return, and not every I/O-return delay
is protected. Relative-cost prediction has no calibrated
uncertainty, and a finite excursion plus MLFQ tail approximates a repeated router.
CI coverage is conditional on one training seed and this balanced synthetic
mixture; 36 validation workloads are modest. Additional capacity is not justified
before resolving the observed tail-risk failure. Future work can test return to
MLFQ at the first legal review with observed unserved arrivals, plus narrowly
targeted I/O-return risk abstention, with fresh preregistered workloads;
it was deliberately deferred rather than tuned after this audit.

Models/data and archived v3 source stay under ignored `artifacts/dynamic_v4_20261019/`.
Protocol/static/family selection precede audit. `research_summary.json`, training
reports, `audit/workloads.csv`, `previous_v3.json`, and `verification.json` contain
complete metrics, CIs, family starvation/switching, group IDs, and checksums.
Reproduction instructions are in the repository README. Synthetic success would
still require locked real-trace validation before final model selection or promotion.
