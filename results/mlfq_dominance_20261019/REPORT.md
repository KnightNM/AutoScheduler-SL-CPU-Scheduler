# Why static MLFQ dominates: diagnostic audit

**MLFQ genuinely wins the frozen five-action comparison on all 1,000 workloads,
but it is not universally optimal. Dynamic switching has measurable simulation
headroom; the current startup policy and training objective obscure it.** No
models were fitted, production policies changed, or existing artifacts replaced.
All findings are post-hoc synthetic diagnostics, not real-kernel evidence or a
new model-selection result.

**Implementation, scoring, and parameters.** Independent static/dynamic parity,
CPU conservation, idle-time, switch-charge, and waiting-time checks passed on
1,750 policy/workload cases. Instrumented cost-tree replay reproduced the
original timelines and decisions on all 1,000 evaluation workloads. No scoring
metric has a degenerate normalization range in this evaluation.

| Diagnostic change only | MLFQ static wins / 1,000 | Interpretation |
|---|---:|---|
| Frozen parameters and six-reference bounds | 1,000 | Original result reproduces |
| Same parameters, five eligible reference bounds | 998 | RR wins two close tradeoffs |
| Same parameters, seven static reference bounds | 1,000 | Advantage survives including MLFQ in bounds |
| Equal zero context-switch charge, six bounds | 968 | Priority/Priority-RR/RR/FCFS also win |
| Equal one-tick charge, six bounds | 0 | FCFS/Priority win; nonzero-cost MLFQ defect caveat below |

Only Priority RR charges one tick in the frozen contract; every other eligible
policy charges zero. Implementations obey those choices. MLFQ versus RR is a
fair **zero-cost** comparison: MLFQ reduces mean waiting and turnaround by
9.889 ticks and mean response by 10.548. Universal dominance over all policies
depends partly on the scoring scale and overhead model, not a kernel property.

Parameters are loaded consistently and not secretly changed for MLFQ. They are
also not optimal: a predeclared sensitivity scan gives RR quantum 1 a mean score
of 0.196035, with 356 wins against frozen MLFQ, versus RR quantum 2's 0.220684.
MLFQ `(1,2,4)`/aging 40 scores 0.146381 and wins all 1,000 against frozen
`(2,4,8)`/aging 20. **These are audit variants, not chosen replacements.** Their
large improvement shows that static parameter headroom exceeds the observed
learned-controller gain, especially when frequent dispatches are free. No
parameters may be selected from this already-examined evaluation set.

**Workload coverage and genuine counterexamples.** Every frozen stratum below
retains MLFQ as its static winner. The positive score-gap ranges show that the
advantage varies substantially; complete counts and metrics are in `strata.csv`.

| Breakdown | Strata | Mean RR-minus-MLFQ score range |
|---|---|---:|
| First workload profile | All five named profiles | +0.01744 to +0.04066 |
| Process count | 30, 32, 34, 36 | +0.02439 to +0.03309 |
| Arrival-rate thirds | 0.508–0.857 arrivals/tick overall | +0.02455 to +0.03067 |
| Mean CPU-burst thirds | 2.832–15.120 ticks overall | +0.02503 to +0.03042 |
| CPU-burst variation thirds | CV 0.447–1.474 overall | +0.02416 to +0.03224 |
| I/O-to-CPU ratio thirds | 0.103–1.826 overall | +0.02497 to +0.03031 |

The ten unordered profile combinations are also reported separately. CPU-first
workloads have the largest RR disadvantage; interactive-first have the smallest.
The generator remains narrow despite these variations: 30–36 processes, three
distinct cohorts injected at 0/20/40, all arrivals finished by tick 59, bounded
CPU bursts of at most 30, and no long sustained late-arrival regimes. Offered
CPU work during the arrival span is 6.8–18.5 times single-CPU capacity.
**91.2% of router reviews occur after the final arrival.** This largely tests
initial congestion followed by queue draining, rather than repeated adaptation.

Under the unchanged frozen objective, no other static action beats MLFQ in the
original 1,000. Nevertheless:

- With eligible-only normalization, RR wins seeds `2026000479` and
  `2026000532` by 0.000472 and 0.000037. It has lower waiting/turnaround but
  worse response; normalization changes the tradeoff, not the execution.
- On 144 separate development probes, 35 have a strictly better eligible action:
  RR 20, FCFS 11, Priority 2, Priority RR 2. These probes never enter evaluation
  or training (one representative winner per probe, with ties broken by registry
  order). A tiny example has three simultaneous jobs, each with CPU bursts
  `(20,20,20)` and I/O `(100,100)`: FCFS scores 0.250000 versus MLFQ 0.571811.
  Long-I/O and homogeneous/sparse workloads expose regimes missing from the
  original three-profile mixture. Witness inputs are retained in `diagnostics.json`.

**Controlled switching opportunity.** These controls reuse the saved tree and
unchanged score bounds. The MLFQ-start control changes only initialization in
the diagnostic runner; production still starts in RR. Dispatch boundaries,
20-tick dwell, and the tree's existing 0.005 predicted margin remain enforced.

| Control | Mean score | Mean workload P95, ticks | Mean starvation count |
|---|---:|---:|---:|
| Continuous MLFQ | 0.192442 | 35.8518 | 32.307 |
| RR, then permanent MLFQ at first allowed review | 0.201005 | 37.2286 | 32.320 |
| Saved tree, production RR startup | 0.216191 | 51.6485 | 32.287 |
| Same saved tree, MLFQ startup | **0.187173** | **35.8518** | **32.307** |

The last control improves mean score by **2.74%**, paired difference
**−0.005270 [−0.005807, −0.004729]**. It wins 699 workloads, ties 102, loses 199;
none has increased P95 response or starvation. It demonstrates an observed-state
controller opportunity, but is post-hoc and lacks a new independent validation
or end-to-end latency gate. It does not authorize changing production startup.

A separate hindsight search examines eight safe MLFQ review boundaries on
100 prespecified workloads, indices `0,10,...,990`. A single permanent departure
to Priority/FCFS improves all 100 while constraining P95 and starvation not to
regress; median departure is tick 276. Requiring at least 0.005 **realized** gain
accepts 91 switches; across all 100 workloads, including nine no-switch cases,
the mean difference is −0.025933 [−0.030159, −0.021791]. A
20-tick excursion followed by MLFQ also has headroom, but reentry resets feedback
state. The permanent-departure result avoids that explanation. These searches
use future outcomes and are **opportunity witnesses, not deployable policies**;
realized-gain filtering is not a calibrated prediction/confidence guarantee.

**Why the tree switches 3.614 times per workload.** All 3,614 accepted switches
occur after the final arrival; median switch time is tick 460. The transitions
are RR→Priority 1,280; Priority→RR 386; Priority→MLFQ 1,048; MLFQ→Priority 900.
There is no direct RR→MLFQ transition. Consequently the production-start model
retains RR through the response-sensitive arrival period and cannot recover
first-response delays with late switching.

Churn is not automatically harmful: forcing the tree to remain in MLFQ once
entered scores 0.217792, slightly worse than its original 0.216191. The issue is
poorly targeted decisions, not simply too many switches. The tree ignores active
policy and priority-mean inputs, puts 59.8% of importance on remaining dwell, and
has no uncertainty estimate or explicit reconfiguration cost. Its mean predicted
accepted advantage is 0.1178 against a 0.005 margin.

For 179 sampled first/last accepted switches, 55 are worse than staying under
the original label objective; 56 are worse under a 20-tick action followed by
MLFQ. In **118/179** cases, the original ten-tick label switches back to RR
before the controller's twenty-tick dwell could permit it. Another 18 trials
finish early and therefore do not violate dwell. Per-state local
min/max labels also use different metric bounds from full-workload evaluation.
Thus the tree optimizes a short RR-continuation counterfactual that does not
match a safe MLFQ-baseline controller. Simple feature-range checks find only
35 out-of-range feature flags in 50,371 reviews; range extrapolation alone does
not explain failure, although joint-state and policy occupancy mismatch remain.

**Defects versus limitations, and the smallest next changes.** Two reproducible
defects were left unfixed in this investigation:

1. MLFQ aging resets the timestamp used by ready-wait features. A process
   continuously ready for 21 ticks is reported as waiting 1 tick after promotion.
   Static completion-based waiting metrics remain correct. Separate the aging
   clock from the original ready-enqueue clock, with a regression test, before
   generating another dataset. Changing this feature only at inference would
   mismatch the saved model; do not silently do that.
2. Hypothetical nonzero-cost MLFQ can select before switch overhead, admit new
   higher-level work during overhead, then record zero service and another
   charged switch. This occurs in 15/1,000 equal-cost-one probes. Fix and
   independently test overhead-boundary dispatch semantics before treating
   that sensitivity as a physically fair alternative. Frozen cost-zero MLFQ
   is unaffected.

Before another fit, implement a **versioned development** comparison that makes
initial/fallback MLFQ explicit and compares against continuous MLFQ; align labels
to feasible dwell/dispatch timing and MLFQ continuation, using fixed bounds and
baseline-relative advantage. Keep the no-change action and separate dwell-blocked
rows from actionable learning diagnostics. Establish an observed-state margin
calibration on development data rather than weakening the frozen gates.

Then expand development-only regimes (sustained arrivals, low load, homogeneous
batch, long I/O, and repeated separated phase changes) and test whether useful
action advantages survive against strong static controls and consistent overhead
assumptions. The original benchmark has real static signal, but insufficient
regime diversity for claims about general desktop adaptation. Static parameter
controls must remain in the comparison. None of this permits synthetic final
real-data selection, altering frozen weights/test sets, or kernel-performance
claims. No larger model/framework is justified yet.

**Validation and reproduction.** Fifty-one targeted tests pass without fitting a
model, in addition to 1,750 randomized accounting cases and 1,000 exact router
replays. Protected production sources, frozen config, models, training rows,
and previous evaluation files match their pre-audit checksums. Run from the repo
root, choosing fresh paths when outputs already exist:

```bash
.venv/bin/python tools/diagnose_mlfq.py --output /tmp/new-mlfq-diagnostics
.venv/bin/python tools/audit_mlfq_accounting.py --output /tmp/new-mlfq-accounting.json
.venv/bin/python tools/audit_mlfq_accounting.py --parameter-scan-only --output /tmp/new-parameter-audit.json
.venv/bin/python -m unittest tests.test_mlfq_diagnostics tests.test_mlfq tests.test_schedulers tests.test_srtf -v
```

`diagnostics.json`, `accounting_sensitivity.json`, `parameter_sensitivity.json`,
`safety_and_route_summary.json`, and the companion CSVs retain the detailed
evidence. **Proceed with the small correctness/objective/control changes above;
do not retrain or promote a new controller on the basis of this audit.**
