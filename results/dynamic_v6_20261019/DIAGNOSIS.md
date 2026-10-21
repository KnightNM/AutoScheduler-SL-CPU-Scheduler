# Final v5 failure diagnosis

The archived v5 source and original cost model reproduce all three previously
identified P95 failures exactly. These old workloads are diagnosis only; they
are not used for v6 fitting or selection. `diagnosis.json` contains both complete
timelines, every process arrival/first dispatch, response cutoff crossings, and
all decision features. Reproduce with:

```bash
.venv/bin/python tools/diagnose_dynamic_v6.py --output /tmp/v6-diagnosis.json
```

| Old workload seed | Priority departure | Observed distinct arrivals before departure | Quiet age | Ready / unserved | P95 dynamic / static |
|---|---:|---|---:|---:|---:|
| 9703000019 | 52 | 13, 23, 28, 31 | 21 | 3 / 0 | 1 / 0 |
| 9703000085 | 43 | 6 | 37 | 1 / 0 | 19.30 / 1 |
| 9703000103 | 51 | 9, 21, 28 | 23 | 2 / 0 | 19.55 / 1 |

In the first case, Priority dispatches P2 at 52–56 and P1 at 56–59.
P5 arrives at 54 but first runs at 59, versus 54 under static MLFQ. The review
at 71 remains dwell-blocked by one tick; return occurs at the next legal review,
80. P6 first runs at 81 versus 80, demonstrating effects that persist after return.

In the second case, Priority runs P2 at 46–54 and P3 at 54–62. At 54 there are
three unserved ready jobs and nine dwell ticks left; at 62, three remain with
oldest first wait nine and one dwell tick left. P4 then occupies 64–81, delaying
legal return until 81. P5 arrives at 54 and first runs at 81 versus 55 under MLFQ;
P4 arrives at 53 and first runs at 64 versus 54. Idle time at 44–46 does not
automatically reset the admitted excursion. Only one arrival was observable at
departure: no reliable interarrival-rate estimate can identify its future burst.

In the third case, P1 occupies 51–57, P8 57–64, then P4 64–72.
At 64, four unserved jobs have oldest wait 12 and seven dwell ticks remain.
P5/P6 arrive at 52/53 and first run at 72/73, both response 20 versus zero under
MLFQ. Return at 72 is the first legal reviewed dispatch boundary.

The shared mechanism is an arrival lull mistaken for a sufficiently stable
period, followed by irreversible dwell/non-preemptive exposure. The departure
first-service guard is correct: every currently ready job had already run.
Protection returns cannot undo that exposure. Queue wait quantiles alone do not
solve it: the second departure has ready-wait P95 zero.

The sole prespecified correction requires **two quiet minimum-dwell intervals**,
40 ticks here, before an outgoing MLFQ excursion, instead of one. This adds a
conservative quiet confirmation interval before committing to another dwell.
It is a heuristic, not an arrival prediction or guarantee. It blocks these three
departures using observed timestamps alone and remains permissive after longer
quiet periods. No family, seed, future arrival, or true CPU duration enters it.
The value is fixed before the fresh experiment; no window search is performed.

The post-audit controlled ablation in `sensitivity.json` keeps the v5 model,
MLFQ parameters, and workload inputs fixed and changes only this guard in a
disposable archived-runtime process. It is explanatory evidence, not another
trained candidate or post-audit selection opportunity. Its results and tradeoff
are reported in `REPORT.md`.
