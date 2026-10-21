# Dynamic ML v5: response tails improve, acceptance still fails

**SYNTHETIC_DEVELOPMENT_ONLY. No model promoted. Recommend tuned static MLFQ.**

On 240 fresh development workloads, the v5 cost tree reduces mean workload P95
first response **50.87%** versus v4, from 15.55938 to **7.64500** ticks. It removes
**98.05% of v4's P95 excess** over tuned MLFQ and retains **88.49% of v4's weighted-score
advantage** over that baseline. However, three sustained-arrival workloads regress
relative to tuned MLFQ. The strict P95 acceptance gate fails; development eligibility
does not override the fresh-audit failure. No post-audit retuning occurs.

## Diagnosis and smallest justified changes

The archived v4 implementation reproduces all **240 saved P95 measurements**
from its two models on the old 120-workload development audit. Repeated changes
and sustained arrivals account for **92.49%** of positive cost-tree P95 excess.
The causes extend beyond the original first-service departure guard:

- Legal MLFQ returns are missed or vetoed by the learned cost margin. For seed
  8403000040, MLFQ requests at ticks 294 and 339 are rejected despite 52/97 ticks
  of observed first-service waiting. P26 arrives at 245 and first runs at 399,
  versus 250 under tuned MLFQ. The departure at 231 had no unserved ready jobs.
- Dwell and non-preemptive dispatch delays occur before a legal return is
  possible. Chaining policies can restart dwell. No later guard can erase this delay.
- Priority-RR overhead contributes to 16 of the classifier's 19 regressed jobs;
  none of those jobs encounters a missed legal MLFQ return. Cost-tree regressions
  involve no charged switch overhead. Earlier policy choices also alter queues
  for jobs arriving after MLFQ resumes.

[DIAGNOSIS.md](DIAGNOSIS.md) documents arrivals, first dispatches, P95-cutoff
crossers, ready waits, review decisions, pressure, dwell, and overhead. Full
representative traces and family/workload summaries are under `diagnosis/`.
They are retrospective explanations, never controller inputs.

The active v5 pipeline adds:

1. **Observed admission risk:** retain the unserved-ready departure guard;
   require one minimum-dwell interval of quiet since the last observed arrival.
   Also hold MLFQ during I/O returns with competing ready jobs and ready-wait P95
   at least one review interval. Quiet low-pressure switches remain possible.
2. **Bounded excursions:** at the first legal review after minimum dwell,
   return to MLFQ rather than letting no-switch, another policy, confidence, or
   learned margin renew the excursion. Unserved counts, oldest first wait,
   queue quantiles, and recent arrivals request protective return earlier, but
   dwell and safe dispatch still take precedence. Safety returns bypass the
   learned margin; ordinary learned departures retain it.
3. **Consistent training:** the same rules govern runtime, mixed/pilot occupancy,
   and feasible action targets. Targets retain the unchanged weighted-score
   objective, explicit no-switch, and MLFQ continuation after the finite action.
   A protected configuration requires that target horizon equal minimum dwell.
4. **Strict selection:** only development-eligible families can be selected.
   Failed candidates may be saved for diagnosis but are marked diagnostic-only.
   The evaluated train-only tree is saved without a refit that could invalidate
   its safety measurements. CLI RR-relative eligibility is labeled separately.
5. **Observed-only schema 5:** nineteen inputs add elapsed time since the last
   released arrival to v4's queue/history/first-service features. No future
   arrivals, true remaining CPU/I/O, declared totals, or post-decision outcomes
   are inputs. Earlier saved models are rejected by the active loader; v4 is
   replayed in an isolated original-source process without editing metadata.

## Frozen development experiment

The development generator and balanced six-family distribution are unchanged;
only seeds are new. This avoids filtering for favorable outcomes or introducing
a distribution change to manufacture improvement. Counts remain 3/6/12/24/48.

- **Training:** 144 trace groups, seed 9701; grouped **100/22/22** train/validation/test.
  Split precedes pilot fitting. **3,393 mixed + 3,889 train-only pilot = 7,282 rows.**
- **Whole-workload validation:** 84 independent seed-9702 workloads, 14 per family.
  Six classifier candidates: depth 3/5/8, ordinary/balanced weights, leaf 10.
  Three cost trees: depth 3/5/8, leaf 10. No forest, neural model, or new framework.
- **Static comparator:** the existing nine-setting development grid selects
  MLFQ **quanta `(1,2,4)`, aging 40**, validation score 0.166405. It is stronger
  than the other eligible statics. Experimental router MLFQ uses these same
  parameters; default registry and real-data configuration remain unchanged.
- **Frozen selection:** one of three cost trees qualifies, **depth 3/leaf 10**.
  Validation score 0.137060, P95 **6.56488**, identical to tuned MLFQ, with lower
  starvation. All six classifier settings fail to establish a primary score
  improvement; its retained depth-8 ordinary-weight tree is diagnostic-only.
- **Audit:** 240 fresh seed-9703 workloads, 40 per family, after selection.
  Original v4 cost-tree replay uses the identical input workloads. The protected
  no-model control exactly matches tuned MLFQ on all 240 workloads.

Score weights remain waiting .30, response .25, turnaround .20, utilization .15,
throughput .10. Normalization remains the original six static reference bounds;
SJF/SRTF are oracle bounds only. Confidence .8, margin .005, epoch 10, dwell 20,
and gate thresholds are unchanged. Primary score requires paired CI upper bound
`<0`; primary P95 upper bound `<=0`; mean starvation cannot increase; largest
workload routing P99 must be strictly `<10 ms`. Original RR-relative gates remain.
No previously examined 1,000-workload benchmark or locked real trace informs
training, tuning, or the audit. The prior v4 audit is diagnosis evidence only.

## Same-workload before/after

Lower is better. P95 is the **mean of workload process first-response P95s**, in
simulator ticks. Worst is the empirical maximum first response across all jobs;
it is not a universal bound. Starvation retains the existing report-only
waiting-time-greater-than-three-times-CPU criterion.

| Scheduler | Score | Mean workload P95 | Worst first response | Starvation/workload | Switches/workload | Pooled routing P99, ms |
|---|---:|---:|---:|---:|---:|---:|
| Dynamic ML v4 cost tree | 0.131767 | 15.55938 | 88 | 13.54583 | 4.79167 | 0.5090 |
| V5 diagnostic classifier | 0.167421 | 7.58042 | 47 | 14.06250 | 0.26667 | 0.5552 |
| V5 development-selected cost tree | **0.135887** | **7.64500** | **47** | **13.67917** | **3.85417** | **0.5207** |
| Tuned static MLFQ | 0.167564 | **7.48729** | **47** | 14.06667 | 0 | — |
| Default MLFQ | 0.181475 | 18.11854 | 94 | 14.54583 | 0 | — |
| FCFS | 0.295652 | 172.49542 | 1363 | 13.66667 | 0 | — |
| RR2 | 0.213036 | 22.03854 | 94 | 15.00417 | 0 | — |
| Priority | 0.292300 | 262.80250 | 1979 | 12.22500 | 0 | — |
| Priority-RR | 0.844964 | 41.48375 | 141 | 15.91250 | 0 | — |

V5 cost P95 improves in **64** workloads versus v4, ties in **176**, and regresses
in **zero**. Versus tuned MLFQ it ties in **237** and regresses in **three**.
Its score is **18.90% lower than tuned MLFQ**, but **3.13% higher than v4** by point
estimate. The score difference versus v4 is uncertain; this is not proof of no
score regression. Aggregate benefit retention is 88.49%, not 100%.

Paired percentile workload bootstrap: 10,000 resamples, seed 2027, 95% intervals.

| Cost-tree difference | Versus tuned MLFQ [CI] | Versus Dynamic ML v4 [CI] |
|---|---|---|
| Weighted score | −0.031676 [−0.040392, −0.023612] | +0.004120 [−0.011119, +0.018617] |
| Mean workload P95 | **+0.157708 [0, +0.389583]** | **−7.914375 [−10.080078, −5.885365]** |
| Mean workload worst response | +0.204167 [0, +0.512500] | −8.858333 [−11.258542, −6.629167] |
| Starvation/workload | −0.387500 [−0.487500, −0.295833] | +0.133333 [−0.091667, +0.350000] |
| Switches/workload | +3.854167 [2.762500, 5.079271] | −0.937500 [−2.029271, +0.229271] |

Matching the global worst of 47 does not establish per-workload worst-response
non-regression: its mean is **8.25833 versus 8.05417** under tuned MLFQ. Three
actual response regressions and the positive P95 CI upper bound fail the hard gate.

## Family results

Each family has 40 fresh workloads. Cells show **score / mean workload P95**.

| Family | Dynamic v4 | V5 cost tree | Tuned MLFQ | V5 starvation / switches |
|---|---|---|---|---|
| Mixed cohorts | 0.152487 / 10.99500 | 0.076950 / 7.35000 | 0.075113 / 7.35000 | 17.925 / 0.550 |
| Sustained arrivals | 0.209868 / 14.95125 | 0.183824 / **1.60875** | 0.183184 / **0.66250** | 14.050 / 0.300 |
| Repeated changes | 0.176468 / 32.66625 | 0.194046 / **2.16750** | 0.212703 / **2.16750** | 12.325 / 1.900 |
| Homogeneous batch | 0.069274 / 19.42750 | **0.091344 / 19.42750** | 0.248662 / 19.42750 | 19.600 / **18.425** |
| Long I/O | 0.182507 / 15.31625 | 0.269160 / 15.31625 | 0.285720 / 15.31625 | 18.175 / 1.950 |
| Low load | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |

Family P95 changes versus v4: mixed **−3.645 [−7.14875, −0.95366]**;
repeated **−30.49875 [−38.41881, −22.53106]**;
sustained **−13.34250 [−17.69378, −9.34622]**. Others tie exactly.
Against tuned MLFQ, only sustained P95 regresses:
**+0.94625 [0, 2.33125]**. These exploratory family CIs do not select the model.

Tradeoffs matter. Long-I/O score worsens versus v4 by **+0.086652
[0.054709, 0.118783]** without improving first-response P95. Conservative
excursions sacrifice much of that family's prior gain. Batch retains substantial
score benefit but switches **18.425** times per workload versus v4's 7.575.
The simulation has no added generic policy-reconfiguration charge; these gains
cannot be assumed to survive real switching overhead. Repeated-change score
loses some v4 gain while eliminating its mean P95 excess.

## Remaining failures and acceptance

The three v5 cost regressions are sustained-arrival seeds **9703000019,
9703000085, 9703000103**: P95 excess **1.00, 18.30, 18.55** ticks. All pass through
a quiet observed interval before later arrivals. For seed 9703000103, Priority
is admitted at 51 after 23 quiet ticks with zero unserved jobs. P5 arrives at 52.
The review at 64 requests MLFQ, but minimum dwell has seven ticks left. Return
occurs at the first legal review, 72; P5 first runs then, response 20 versus
zero under MLFQ. The guard and safety return work as specified, but cannot
foresee an arrival or shorten a committed dwell/non-preemptive dispatch.
`residual_diagnosis.json` records all three cases without retuning or replacing timing.

| Gate on fresh audit | Classifier | Cost tree |
|---|---|---|
| Primary weighted-score improvement | fail | pass |
| Primary P95 non-regression | **fail** | **fail** |
| Primary mean starvation | pass | pass |
| Strict routing latency | pass | pass |
| Original RR-relative score / P95 | pass / pass | pass / pass |
| Development eligibility before audit | fail | pass |
| Accepted after audit / promoted | **no / no** | **no / no** |

Maximum workload routing P99 is **0.7546 ms classifier / 1.0503 ms cost**;
pooled P99 is shown above. The no-model control measures 0.2384 ms pooled and
0.4407 ms maximum workload P99, with exactly static schedules. Feature extraction,
prediction, safeguards, and accepted queue rebuild are timed. Static dispatch-only
latencies were not separately measured. None is a Linux controller timing claim.

V5 therefore **does not genuinely outperform tuned MLFQ under the complete
acceptance contract**, despite a significant weighted-score improvement and a
large response improvement over v4. The P95 upper bound is not relaxed because
it is small. No alternative is selected using the audit and no model is promoted.

## Diagnostics, preservation, and limitations

Held-out grouped decision-row accuracy: **70.99% classifier / 19.08% cost**;
tie-aware **79.01% / 83.21%**; action regret **0.002375 / 0.001773**.
The cost tree's lower strict accuracy does not contradict its scheduling gain.
Exact ties affect 57.90% of rows. Labels: No Switch 3,710; Priority 1,640;
FCFS 1,479; RR 305; Priority-RR 148. Full confusion matrices, all nine settings,
validation intervals, class distributions, and group IDs are saved in JSON.

**245 regression tests pass**, including 14 v5 tests for pressure, arrivals,
I/O competition, quiet switches, no-switch expiry, dwell/fallback, nonzero
overhead, observed-only perturbations, runtime/training equivalence, eligibility,
pairing, and unchanged gate boundaries. All **142 paths** covered by combined
historical preservation manifests match; pre-fit source/model hashes match.
Real-config, whitespace check, and AST graph update pass. No frontend, Azure
dataset, prior model/report, score weight, or frozen real protocol changes.

The rules, model, workload sampling, and finite targets change together; this
experiment cannot assign each rule's causal contribution. A quiet interval is
not proof that arrivals have ended. Margin/confidence is not calibrated tail-risk
uncertainty. Bounded excursions and reentry resets trade score against safety;
generic switching costs remain unmodeled. Family CIs are exploratory, and all
CIs condition on one training seed and the synthetic generator. Validation
success on 84 cases did not guarantee safety on 240 independent cases. The
next research question is admission risk for non-preemptive excursions after
arrival lulls, with long-I/O conservatism separately controlled; it is deferred
rather than fitted to these three audit failures. Locked real-trace validation
and end-to-end controller measurements remain mandatory before real deployment.

Models/data are local under ignored `artifacts/dynamic_v5_20261019/`.
`protocol.json`, `static_selection.json`, and `frozen_selection.json` precede
auditing. `research_summary.json`, training JSONs, `audit/workloads.csv`, and
`verification.json` retain full evidence, including per-family paired intervals.
The isolated original v4 replay is in `v4_replay.json`. README reproduction
instructions use fresh output paths and the preserved v4 source/model.
