# V4 first-response diagnosis, before v5 fitting

The archived v4 source and original models reproduce the saved P95 values on
all **240 model/workload pairs**: two models on the 120-workload development audit.
No model is fitted in this phase. This already examined audit informs the
mechanism investigation only; v5 selection and auditing use new seeds.

## Where the regressions occur

| V4 model / family | Mean P95 excess over tuned MLFQ | Regressed workloads / 20 |
|---|---:|---:|
| Cost / repeated changes | +30.3075 | 12 |
| Cost / sustained arrivals | +16.6925 | 15 |
| Cost / mixed cohorts | +3.8150 | 3 |
| Classifier / mixed cohorts | +1.7625 | 3 |
| Classifier / sustained arrivals | +1.2175 | 3 |

Other family P95 differences are zero. Repeated changes contribute 59.64% and
sustained arrivals 32.85% of positive cost-tree P95 excess: **92.49% combined**.

Individual first responses regress for **342 cost-tree jobs**: 331 arrive while
the logged active policy is outside MLFQ, 11 while it is MLFQ. Of these jobs,
84 encounter a legal review that retains another policy, 54 encounter a
dwell-blocked review, and zero encounter charged switch overhead before first
service. These counts overlap and indicate associated mechanisms, not a causal
partition. Earlier policy choices can change queues even after returning to MLFQ.

The classifier regresses for 19 jobs: 18 arrive outside MLFQ, 10 encounter dwell
blocking, and **16 encounter charged switch overhead**. None encounters a missed
legal MLFQ return. This is a different failure pattern from the cost tree.
Removing the departure guard alone would not address either set of failures.

## Representative cost-tree trace: repeated changes, seed 8403000040

The departure at tick 231 is legal and sees zero unserved ready jobs. The later
arrivals are not observable then. The original first-service departure guard
therefore behaves as specified. It cannot guarantee future response safety.

| Review | Active after review | Model request | Accepted | Reason | Unserved ready | Oldest first wait | Queue wait P95 | Recent arrivals | Dwell left |
|---:|---|---|---|---|---:|---:|---:|---:|---:|
| 231 | FCFS | FCFS | yes | accepted | 0 | 0 | 12.40 | 0 | 0 |
| 242 | FCFS | Priority | no | dwell blocked | 4 | 0 | 17.00 | 4 | 9 |
| 250 | FCFS | MLFQ | no | dwell blocked | 9 | 8 | 8.00 | 5 | 1 |
| 294 | FCFS | MLFQ | no | cost margin | 8 | 52 | 52.00 | 0 | 0 |
| 339 | FCFS | MLFQ | no | cost margin | 7 | 97 | 97.00 | 0 | 0 |
| 394 | MLFQ | MLFQ | yes | accepted | 16 | 152 | 151.25 | 10 | 0 |

The switch margin can veto a model's own MLFQ request when predicted advantage
is less than 0.005. A first-service override must be independent of that learned
margin. V5 retains the margin for learned departures and gives safety returns
the same precedence as fallback, while still enforcing dwell and dispatch safety.

| Job | Arrival | V4 first dispatch | V4 response | Tuned MLFQ first dispatch | Tuned response |
|---|---:|---:|---:|---:|---:|
| P21 | 245 | 398 | 153 | 249 | 4 |
| P26 | 245 | 399 | 154 | 250 | 5 |
| P27 | 244 | 397 | 153 | 248 | 4 |

All three exceed the tuned workload's P95 cutoff of 6 and occupy the dynamic
upper tail. Dynamic P95 is **152.65**. The oldest ready wait at legal review 294
is already 52: fixing later vetoes cannot undo earlier dwell/dispatch delay.

## Other witnesses

- **Sustained arrivals, cost, seed 8403000049:** switch to FCFS at 40 despite
  two recent arrivals. P6 arrives at 46, starts at 90 (response 44), versus
  MLFQ start 47 (response 1). At 54 there are three unserved jobs, oldest wait
  13, dwell remaining 6. Legal MLFQ requests at 60/80/90 fail the cost margin.
  A recent-arrival admission gate and a non-renewable excursion address separate
  parts of this mechanism.
- **Same workload, classifier:** switch to Priority-RR at 40. P6 starts at 62,
  response 16, including five ticks of charged context-switch time before its
  first service. Dwell prevents return at 52; fallback returns at 61. Faster
  return alone cannot eliminate overhead already incurred.
- **Mixed cohorts, cost, seed 8403000000:** first-service guard blocks departure
  at 20, but Priority is admitted at 30 after five recent arrivals and five I/O
  returns, with queue P95 wait 22.4. P18/P23 arrive at 43, first run at 76/77,
  versus 46/47 under MLFQ. A review at 56 keeps Priority despite seven unserved
  jobs and zero dwell remaining. Queue and arrival pressure matter even when
  every currently ready job had received some service at departure.
- **Mixed cohorts, classifier, seed 8403000060:** Priority-RR at 20 chains into
  FCFS at 41, restarting dwell. P6 arrives at 43 and starts at 66, versus 43
  under MLFQ. A non-preemptive dispatch and renewed dwell dominate. V5 routes
  the first expired excursion back to MLFQ instead of allowing policy chaining.

## Prespecified response changes

V5 blocks departures until one minimum-dwell interval has elapsed since the
last observed arrival. It also blocks departures during I/O returns with
competing ready jobs and queue P95 wait of at least one review interval. The
original unserved-ready departure guard remains. Counts, oldest first wait,
queue quantiles, and arrival pressure request protective return when first
response pressure appears; minimum dwell still takes precedence.

At the first legal review after minimum dwell, an excursion expires regardless
of model confidence, margin, or no-switch request. This matches the finite
excursion plus MLFQ-continuation target. It preserves safe quiet-period switches
and prevents indefinite renewal; it does not preempt a running non-preemptive
burst or inspect future arrivals/burst lengths. Remaining irreversible dispatch
delays are a modeling limitation to measure, not grounds for weakening gates.

`diagnosis/representatives.json` contains process arrivals/first dispatches,
baseline response cutoffs, per-process dwell/missed-return/overhead annotations,
and review-level unserved waits, observed features, policies, requests, switches,
and protection reasons. `diagnosis/workloads.csv` and `diagnosis/summary.json`
retain all workload and family evidence. These are retrospective analyses;
future outcomes used to explain failures are never passed to controller inputs.
