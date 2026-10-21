# AutoScheduler: Workload-Adaptive CPU Scheduling Simulator

AutoScheduler is a single-CPU research simulator that compares FCFS, SJF, SRTF,
Round Robin, Priority, and Priority-RR, then uses an offline-trained decision tree
to select one algorithm for a new workload.

The project is a simulator, not an operating-system kernel scheduler.

The next research phase validates ML on observed Linux desktop traces. Its
machine-readable contract is `configs/real_desktop_ml.json`; synthetic data is
limited to tests, stress cases, and optional pretraining. Validate the frozen
contract with:

```bash
python main.py real-config
```

See `docs/REAL_DATA_POLICY.md` for source, privacy, and licensing boundaries.
See `docs/OFFLINE_REPLAY_CONTRACT.md` for the trace eligibility and
reconstruction rules used to create offline candidate-screening labels.

### Real Linux trace smoke flow

The collector must run inside the Linux VM because macOS does not expose Linux
scheduler tracepoints. It traces one pinned CPU while running the workload as
the original non-root user:

```bash
sudo /home/knightnm/autoscheduler-tools/capture_linux_trace.sh \
  /home/knightnm/autoscheduler-captures/smoke-cpu-002 0 -- \
  stress-ng --cpu 1 --timeout 5s --metrics-brief
```

For a controlled desktop workload, deploy `tools/run_firefox_probe.sh` and
`workloads/real/firefox_probe/index.html` with the same repository layout in
the VM. Test the visible workload without tracing first:

```bash
/home/knightnm/autoscheduler/tools/run_firefox_probe.sh 8
```

The probe uses an isolated temporary Firefox profile, loads only the local
page, performs deterministic DOM and canvas work, and exits after the requested
duration.

Multiprocess desktop applications may create helpers outside their requested
CPU affinity. Capture all CPUs while retaining CPU 0 as the workload affinity,
then detect migrations during validation:

```bash
sudo /home/knightnm/autoscheduler-tools/capture_linux_trace.sh \
  --all-cpus /home/knightnm/autoscheduler-captures/smoke-firefox-allcpu-001 \
  0 -- /home/knightnm/autoscheduler/tools/run_firefox_probe.sh 10
```

After the all-CPU smoke capture passes, collect one short trace for every real
workload family:

```bash
sudo /home/knightnm/autoscheduler/tools/capture_linux_pilot.sh \
  /home/knightnm/autoscheduler-captures/pilot-001 10
```

The pilot runs wakeup, CPU, I/O, Firefox, compression, and mixed workloads
sequentially. It is pipeline validation only, not the final training dataset.

For the full raw-trace collection, the runner records all CPUs for 30 named
configurations, repeats each configuration ten times, and retains only raw
trace data, metadata, and logs on the VM. It takes about five hours:

```bash
sudo /home/knightnm/autoscheduler/tools/capture_linux_full.sh \
  /home/knightnm/autoscheduler-captures/full-001 60 10
```

Validate the complete 30-configuration matrix without recording data first:

```bash
bash /home/knightnm/autoscheduler/tools/capture_linux_full.sh \
  --dry-run /home/knightnm/autoscheduler-captures/full-001 60 1
```

Do not export uncompressed reports on the VM during collection; its available
storage is reserved for the raw capture set.

After exporting `trace.dat` with `trace-cmd report`, import and validate it:

```bash
python main.py real-trace-import \
  --report data/raw/linux/smoke-cpu-002/trace.txt \
  --metadata data/raw/linux/smoke-cpu-002/metadata.json \
  --output data/processed/linux/smoke-cpu-002.jsonl \
  --trace-id smoke-cpu-002
python main.py real-trace-validate data/processed/linux/smoke-cpu-002.jsonl
```

Raw and processed traces are ignored by Git. Commit only anonymized fixtures,
manifests, checksums, and aggregate results.

### Cleaning and anonymization

Before sharing or modeling canonical traces, create a separate sanitized copy.
The cleaner never changes its inputs. It rejects incomplete traces, replaces
trace and process identifiers, removes machine/user/path/command metadata, and
keeps only scheduling-relevant fields:

```bash
python main.py real-trace-clean \
  data/processed/linux/pilot-001/wakeup-001.jsonl \
  data/processed/linux/pilot-001/cpu-001.jsonl \
  data/processed/linux/pilot-001/io-001.jsonl \
  data/processed/linux/pilot-001/firefox-001.jsonl \
  data/processed/linux/pilot-001/compression-001.jsonl \
  data/processed/linux/pilot-001/mixed-001.jsonl \
  --capture-session pilot-clean \
  --output data/processed/linux/pilot-001/cleaned.jsonl
python main.py real-trace-validate data/processed/linux/pilot-001/cleaned.jsonl
```

Use the cleaned JSONL for feature extraction and offline replay outside the
private capture workspace. Cleaning makes traces shareable for this research
workflow; it does not make a trace safe to publish if its timings themselves
are sensitive.

### Observed-only feature rows

After importing traces, extract decision rows using only events that occurred
before each decision time. This creates inputs, not model labels or performance
claims:

```bash
python main.py real-features \
  data/processed/linux/pilot-001/cleaned.jsonl \
  --output data/processed/linux/pilot-001/observed_features.csv
```

The CSV includes only the feature contract in `configs/real_desktop_ml.json`.
It cannot train a policy model until a separate, valid policy-cost labeling
method exists.

### Leakage-safe trace split

Split feature rows before any model fitting. Rows from the same application,
scenario, and capture session always remain together; this prevents a model
from training on one moment of a trace and being tested on another:

```bash
python main.py real-split \
  data/processed/linux/pilot-001/cleaned_observed_features.csv \
  --output data/processed/linux/pilot-001/split_manifest.json
```

The pilot creates a valid 4/1/1 trace-group smoke split, but it is too small
for model selection or performance claims. Older imported traces without
scenario metadata are isolated by their anonymized trace ID.

### Prototype-only replay labels

The pilot can create offline-replay action-cost rows to exercise the model
pipeline. These rows are explicitly development-only and cannot support a
claim about real Linux scheduler performance:

```bash
python main.py real-dataset \
  data/processed/linux/pilot-001/cleaned.jsonl \
  --output data/processed/linux/pilot-001/pilot_action_costs.csv
```

Run the prototype model bake-off with observed state features plus a proposed
action. Each model predicts the replay cost of that action, then picks the
lowest predicted-cost action for each observed state. The report is development
only: its labels are offline replay estimates, not Linux kernel measurements.

```bash
.venv/bin/python main.py model-bakeoff \
  data/processed/linux/pilot-001/pilot_action_costs.csv \
  --output results/real_desktop_ml/prototype_bakeoff
```

It writes `summary.json`, `candidates.csv`, `prototype_comparison_report.md`,
and `locked_evaluation_report.md` under the output directory. The locked report
returns `INSUFFICIENT_DATA` until it has all 60 grouped locked-test traces
required by the frozen collection contract; it never turns a small pilot into a
passing ML result.

### Synthetic development pipeline

When a real Linux collection is unavailable, exercise the full pipeline with
deterministic trace-shaped development data. It is intentionally marked
`SYNTHETIC_DEVELOPMENT_ONLY`; it can test plumbing, not select a final model.

```bash
.venv/bin/python main.py real-synthetic-capture --repetitions 60 --seed 9001 \
  --output data/processed/synthetic/prototype/raw.jsonl
.venv/bin/python main.py real-trace-clean data/processed/synthetic/prototype/raw.jsonl \
  --capture-session synthetic-prototype --output data/processed/synthetic/prototype/cleaned.jsonl
.venv/bin/python main.py real-features data/processed/synthetic/prototype/cleaned.jsonl \
  --output data/processed/synthetic/prototype/observed_features.csv
.venv/bin/python main.py real-dataset data/processed/synthetic/prototype/cleaned.jsonl \
  --output data/processed/synthetic/prototype/action_costs.csv
.venv/bin/python main.py model-bakeoff data/processed/synthetic/prototype/action_costs.csv \
  --output results/real_desktop_ml/synthetic_prototype
```

### Offline replay workloads

Create deterministic simulator inputs from completed canonical traces. The
output records every rejected trace or process, so exclusions stay auditable:

```bash
python main.py real-replay-build \
  data/processed/linux/pilot-001/wakeup-001.jsonl \
  data/processed/linux/pilot-001/cpu-001.jsonl \
  data/processed/linux/pilot-001/io-001.jsonl \
  data/processed/linux/pilot-001/firefox-001.jsonl \
  data/processed/linux/pilot-001/compression-001.jsonl \
  data/processed/linux/pilot-001/mixed-001.jsonl \
  --output data/processed/linux/pilot-001/offline_replay_manifest.json
```

This is offline candidate screening, not evidence that a policy improves the
real Linux kernel scheduler.

## Features

- Backward-compatible single CPU-burst processes
- Alternating CPU and I/O bursts with blocked-process events
- Deterministic FCFS, non-preemptive SJF, preemptive SRTF, Round Robin, Priority, and Priority-RR policies
- Interactive, batch, CPU-intensive, I/O-intensive, and mixed workloads
- Waiting, response, turnaround, utilization, throughput, idle-time, makespan,
  context-switch, switch-time, and maximum-wait metrics
- Consistent six-policy ML labels and static baseline evaluation
- Offline decision-tree training and held-out evaluation
- CLI comparison tables, timelines, CSV data, JSON summaries, and PNG charts

## Setup

Requires Python 3.10 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Commands

Open interactive presentation menu:

```bash
python main.py demo
```

Use `python main.py demo --no-color` for redirected output or terminals without
ANSI color support. Menu runs only short live comparisons and reads completed
research artifacts; it never starts full training or evaluation automatically.
Choose option `10` for an animated six-policy scheduler race on one generated
workload. Playback is shortened, but final metrics use complete timelines.

Run the original Phase 1 demonstration:

```bash
# Run the demo
python main.py

# Run the test suite
python -m unittest discover -s tests
```

Tune Priority-RR, generate 2,500 six-policy oracle labels, and train the model:

```bash
python main.py train
```

Compare all static policies with the adaptive selection:

```bash
python main.py compare --profile mixed --seed 42
```

Evaluate 1,000 unseen workloads and write `results/` artifacts:

```bash
python main.py evaluate
```

Measure scheduler decision latency across small, medium, and large workloads:

```bash
python main.py latency
```

Train and evaluate safe adaptive routing across changing three-phase workloads:

```bash
python main.py dynamic-train
python main.py dynamic-evaluate
```

Evaluate fixed MLFQ and its decision latency:

```bash
python main.py mlfq-evaluate
python main.py mlfq-latency
```

Run a six-policy experiment without replacing historical results:

```bash
python main.py train --model results/six_policy/model.joblib --dataset results/six_policy/training.csv
python main.py evaluate --model results/six_policy/model.joblib --output results/six_policy
python main.py latency --model results/six_policy/model.joblib --score-summary results/six_policy/summary.json --output results/six_policy/full_latency
```

Use `python main.py <command> --help` to override sample counts, seeds, paths,
or comparison workload size.

## Architecture

- `scheduler/`: stable policy entry points
- `simulator/`: process model, shared event engine, and metrics
- `autoscheduler/workloads.py`: seeded synthetic workload generation
- `autoscheduler/features.py`: pre-simulation feature extraction
- `autoscheduler/evaluation.py`: static comparison and weighted oracle scoring
- `autoscheduler/dataset.py`: labeled CSV dataset generation
- `autoscheduler/model.py`: decision-tree tuning and persistence
- `autoscheduler/adaptive.py`: one-time workload classification and execution
- `autoscheduler/experiments.py`: held-out evaluation and artifacts
- `autoscheduler/dynamic.py`: state-preserving epoch routing and dynamic experiments
- `autoscheduler/benefit.py`: observed-state RR-to-SRTF benefit regression
- `autoscheduler/mlfq_experiment.py`: static MLFQ comparison and decision gates
- `autoscheduler/cli.py`: train, compare, evaluate, and latency commands

## Workload Profiles

| Profile | Main behavior |
|---|---|
| Interactive | Short CPU bursts with repeated I/O waits |
| Batch | Long jobs arriving in compact groups |
| CPU-intensive | Long CPU bursts with little I/O |
| I/O-intensive | Many short CPU bursts separated by longer I/O waits |
| Mixed | Per-process mixture of the other four profiles |

Every generator uses a local seeded random source. Identical profile, seed, and
process count produce identical workloads.

## Model Inputs

The classifier receives only information available before scheduling:

- Process count and arrival rate
- Total CPU-burst mean and variance
- Short-job ratio
- Priority mean and variance
- Mean I/O frequency
- I/O-to-CPU time ratio

Post-simulation metrics are never classifier inputs.

## Oracle Score

ML training labels and held-out evaluation use the same six policies: FCFS,
SJF, SRTF, Round Robin, Priority, and Priority-RR. SJF chooses by total CPU
`burst_time` without preemption. SRTF chooses by the current CPU burst's
`remaining_time` and preempts only for a strictly shorter ready burst at a
new arrival or I/O completion. Priority-RR is tuned on deterministic
seed-42 development workloads, then its configuration is frozen before label
generation and unseen evaluation.

| Metric | Weight |
|---|---:|
| Mean waiting time | 30% |
| Mean response time | 25% |
| Mean turnaround time | 20% |
| CPU-utilization penalty | 15% |
| Throughput penalty | 10% |

The default dataset has 500 workloads per profile. Training uses a seeded,
stratified 70/15/15 train, validation, and test split. Tuning changes only tree
depth and minimum leaf size. It selects the candidate with the lowest validation
mean regret (then lower depth, then larger leaf size), rather than highest
classification accuracy. The best global static comparator is selected from
validation rows and frozen before held-out evaluation.

## Evaluation

Default evaluation uses 200 unseen workloads per profile with a separate seed.
Reports include classification accuracy, score regret against the oracle,
inference time, per-profile summaries, all static baselines, adaptive score, and
oracle score. It also writes `confusion_matrix.csv`, `feature_importance.csv`,
and `diagnostics.png`, alongside `evaluation.csv`, `summary.json`, and
`scores.png`.

`summary.json` records oracle and selected-policy distributions per profile,
the oracle-versus-selected confusion matrix, and mean score/regret for each
static policy, constant SJF, adaptive selection, and the oracle. Adaptive success
requires a lower paired mean score than the frozen static comparator and a 95%
bootstrap confidence interval whose upper bound is below zero. The report uses
10,000 paired resamples with seed 2027, overall and per workload profile. Score
weights remain fixed; changing them requires a separate findings review.

`fairness_metrics.csv` and `fairness.png` report pooled process behavior without
changing scores: P95 and maximum wait, starvation count, priority-class delay,
and post-I/O response delay. Starvation means waiting more than three times a
process's total CPU time. Priority delay covers classes 1 and 2.

`python main.py latency` writes `latency.csv`, `latency_summary.json`, and
`latency.png`. It measures next-ready-process selection for SJF, SRTF, Round Robin,
Priority, and Priority-RR (including SRTF event preemption checks), and feature extraction plus model inference for
Adaptive. CPU execution and metric aggregation are excluded from timed samples.
Every policy must have P99 decision latency strictly below 10 ms for small (12),
medium (100), and large (1,000) workloads. Among gate passers, the lowest
validation-frozen static policy is recommended unless Adaptive passes both the
paired statistical gate and every latency gate.

Priority-RR tuning evaluates nine validation-only settings: quantums `1`, `2`,
`4` and aging intervals `4`, `8`, `12`. It promotes I/O-returning processes one
priority class and charges one tick for each process switch. It passes only when
held-out mean score and maximum individual waiting time are both strictly lower
than SJF.

The historical corrected five-policy experiment is under `results/five_policy_consistent/`.
Six-policy results are stored separately under `results/six_policy/`; scores
cannot be compared directly across these sets because normalization depends on
the candidates. Previously saved models must be retrained for the new policy set. Root-level
results are historical four-policy/five-policy-mismatch artifacts and are not
the primary research evidence. Corrected evidence recommends Round Robin; the
adaptive selector does not beat it.

With six policies (training seed 42, 2,500 workloads; evaluation seed 2026,
1,000 workloads), Round Robin has mean score 0.13221, SRTF 0.16773, and
Adaptive 0.13188. The paired Adaptive-minus-frozen-static 95% interval crosses
zero, so the adaptive statistical gate remains false. Full six-policy latency
results are in `results/six_policy/full_latency/`: seed 3030, 20 measured
samples per profile, five warmups, and P99 below 10 ms for every measured
policy at every size. Large-workload P99 is 0.0611 ms for Round Robin and
6.5507 ms for Adaptive. Round Robin remains recommended. The separate
one-sample latency smoke artifacts remain in `results/six_policy/`.

## Dynamic Routing Experiment

The corrected router defaults to the deployable policy set: FCFS, Round Robin
quantum 2, Priority, Priority RR `(2, 8, 1)`, and MLFQ `(2, 4, 8)` with aging 20.
The six-policy simulation comparison remains available. Pass
`dynamic-train --policy-track oracle_simulation` to explicitly train its oracle
simulation router; SJF and SRTF are never deployable claims.

Inputs contain observed completed-burst statistics, cumulative CPU service,
ready/blocked queue sizes, priorities, waits, arrivals, I/O returns, and current
router policy/dwell state. They exclude remaining work and future events. The
schema-5 inputs include first-service ready count/wait, ready-wait quantiles,
and elapsed time since the last observed arrival.
Departures from MLFQ are blocked while an observed ready job has received no CPU;
switching remains possible after first service. An explicit `No Switch` action
holds the current policy. The cost tree exposes benefits relative to MLFQ continuation.
With `--response-tail-protection`, departures also require a quiet arrival
interval and avoid I/O-return pressure. Excursions return to MLFQ at the first
legal review after minimum dwell; learned margins and no-switch cannot renew
them. Safety returns retain dwell and dispatch boundaries. This option requires
`--fallback-policy MLFQ`; historical RR/hold defaults remain available.
The router starts with Round Robin by default and switches only at safe dispatch
boundaries. `--initial-policy MLFQ --fallback-policy MLFQ` explicitly selects
MLFQ startup and low-confidence/unavailable-model fallback. The historical
default fallback, `hold`, keeps the current policy. Fallback also respects dwell.
Classifiers retain confidence and dwell safeguards. Cost trees retain dwell and
a predicted cost-improvement margin of 0.005; that margin is not a probability.

Development traces include mixed cohorts, sustained arrivals, low load, long
I/O, repeated changes, and homogeneous batch controls. Family and rollout policy
are crossed independently. The default `--workload-suite v4` adds counts
3/6/12/24/48, stochastic arrivals, and sparse long-I/O controls, without outcome
filtering. `--workload-suite development` retains the v3 development generator;
`--workload-suite historical` retains the older
cohort-only development generator. Training
includes each eligible static rollout, exploration, and train-only pilot model
rollouts. Whole trace seeds stay in disjoint 70/15/15 groups, recorded before
fitting. Candidate selection prioritizes safety eligibility, then realized scheduling scores on separate
development workloads. The static comparator is selected from whole-workload
development performance. Accuracy, confusion, tie ambiguity, and regret remain
diagnostics rather than the optimization target.

`dynamic-train --model-kind policy_cost` is the default. Use
`--model-kind classifier` to compare the decision-tree classifier, including
balanced-class candidates. Router settings are explicit by default; the optional
`--tune-router` retains the older synthetic router search. New models use schema
version 5 and paths under `artifacts/dynamic_v5/`; evaluation defaults to
`results/dynamic_v5/`. Dynamic training saves the evaluated train-only model
without a refit that could invalidate its measured safety. Loading
checks features, estimator dimensions, policy order/parameters, and frozen
router configuration. Schema-2/3/4 and historical five/six-policy dynamic models require
retraining and are deliberately rejected by the active loader.
If every candidate fails development constraints, saved models are explicitly
diagnostic-only and family selection returns no ML candidate. Original RR-relative
eligibility does not imply development eligibility or authorize promotion.

Corrected labels exclude dwell-blocked states. Each action persists through
minimum dwell until the next legal global review and dispatch boundary, then
continues with MLFQ. Idle jumps are reviewed before late jobs dispatch. Costs
use fixed full-workload reference bounds and subtract immediate MLFQ continuation
from the same prefix. Future simulator outcomes supply offline targets only;
they are never inputs. Queue aging has its own clock and preserves observed
ready waiting time. MLFQ reselects after nonzero dispatch overhead without
charging twice or recording a zero-service dispatch.

Evaluation preserves the original seed-2026 workload generator. Score weights
and gate thresholds are unchanged. Metric normalization uses bounds fixed by
the six static simulation references, so adding a candidate cannot change the
scale. Reports retain the original Adaptive-minus-RR gates and add comparisons
against the frozen eligible static comparator, starvation, signed regret to
the best eligible static policy on each workload, switching, and decision time.
Synthetic ticks are not kernel measurements.

The historical schema-2 comparison is documented in
[`results/dynamic_v2_20261019/REPORT.md`](results/dynamic_v2_20261019/REPORT.md).
The historical schema-3 corrective experiment is documented in
[`results/dynamic_v3_20261019/REPORT.md`](results/dynamic_v3_20261019/REPORT.md).
The historical focused safety-constrained experiment is documented in
[`results/dynamic_v4_20261019/REPORT.md`](results/dynamic_v4_20261019/REPORT.md).
The response-tail investigation and v5 experiment are documented in
[`results/dynamic_v5_20261019/DIAGNOSIS.md`](results/dynamic_v5_20261019/DIAGNOSIS.md)
and [`results/dynamic_v5_20261019/REPORT.md`](results/dynamic_v5_20261019/REPORT.md).
V5 uses 144/84/240 fresh training/validation/audit workloads with the unchanged
balanced development generator. It does not tune on the previous 1,000-workload
benchmark or locked real traces. Experimental MLFQ parameters match the
development-selected static control; registry and real-contract defaults remain
unchanged. Reproduce with the preserved local v4 cost model and original source:

```bash
mkdir -p artifacts/dynamic_v5_reproduction
cp -a artifacts/dynamic_v5_20261019/before_source artifacts/dynamic_v5_reproduction/
.venv/bin/python -m autoscheduler.dynamic_v5_experiment \
  --output results/dynamic_v5_reproduction --artifacts artifacts/dynamic_v5_reproduction
```

It remains **SYNTHETIC_DEVELOPMENT_ONLY**. Final real-data selection still
requires cleaned captures, the real grouped split, and the frozen real-desktop
gates. The Azure pipeline and real replay label provenance are unchanged.

The final synthetic checkpoint is
[`results/dynamic_v6_20261019/REPORT.md`](results/dynamic_v6_20261019/REPORT.md).
V6 tests a longer observed arrival-quiet admission window. It is **not promoted**:
the new model regresses against v5 and the prior frozen static response envelope,
despite passing its own development-selected-comparator gates. Keep v5 as a
research candidate and MLFQ `(1,2,4)`, aging 40, as the simulator recommendation.
Synthetic tuning is closed; the next phase is the interactive dashboard.

Future backend/frontend integrations should read
[`configs/research_status.json`](configs/research_status.json) for versioned
model status, artifact checksums, dataset-scoped metrics with units, gates, and
recommendations. Regenerate it with
`.venv/bin/python -m autoscheduler.research_status`; no ML model is approved for
deployment and simulator ticks are not Linux response-time measurements.

`artifacts/dynamic_model.json`, `results/dynamic/`, and
`results/six_policy/dynamic*` are preserved historical artifacts. Their old
accuracy uses a different label set/split, and their scores used candidate-
dependent normalization. They must not be compared directly with corrected
scores or presented as deployable-policy evidence.

## RR-versus-SRTF Benefit Experiment

This conservative experiment starts with a development-tuned Round Robin
quantum, observes only runtime state for 5, 10, or 20 ticks, then either keeps
RR or switches once to SRTF. The decision-tree regressor predicts
`SRTF score - RR score`; SRTF is chosen only when the prediction clears the
validation-tuned safety margin. Features exclude future arrivals, declared
total CPU/I/O work, and true remaining burst time.

```bash
python main.py benefit-train
python main.py benefit-evaluate
python main.py benefit-latency
```

Training uses seed 42 with trace-disjoint 70/15/15 splits. Evaluation uses
1,000 unseen workloads from seed 4040 and 10,000 paired bootstrap samples from
seed 4041. Scores use bounds frozen by the original six static policies, so
adding the selector cannot change RR's normalized score. Latency uses 12, 100,
and 1,000-process workloads, 20 measured samples per profile, and five warmups.

The ML selector is eligible only if it lowers mean score by at least 1% versus
tuned RR, its paired 95% confidence interval is entirely below zero, and every
decision-latency P99 is below 10 ms. RR remains the recommendation when any
gate fails. Artifacts are written to `results/rr_srtf_benefit/`; prior static
and dynamic results are preserved.

Seed-4040 result: RR quantum 1, observation window 20, and margin 0.0025 were
selected. Mean score fell from 0.111959 for tuned RR to 0.037037 (66.92%);
the paired difference was -0.074922 with 95% CI [-0.077475, -0.072355]. The
largest measured P99 was 0.358896 ms, so all three gates pass. However, the
model selected SRTF for 98.1% of workloads. This proves the observed
RR-then-SRTF policy beats RR under the synthetic objective, but does not yet
prove ML is necessary; a fixed switch-at-20 hybrid is the next required
baseline.

## Static MLFQ Baseline

MLFQ uses three FIFO queues with quanta `(2, 4, 8)`. New and I/O-returning
processes enter the top queue. Full quantum use moves a process down; waiting
20 ticks moves it up. Higher queues preempt lower queues while preserving the
interrupted process's unused quantum.

`mlfq-evaluate` compares MLFQ with tuned RR, direct SRTF, and fixed
RR-for-20-ticks-then-SRTF. It uses 1,000 seed-6060 synthetic workloads with
randomized process counts and the original frozen six-policy score bounds.
These workloads are more varied synthetic tests, not real kernel traces.
`mlfq-latency` uses seed 6062, 20 samples per profile, five warmups, and
12/100/1,000-process workloads.

Seed-6060 result: RR-20-SRTF wins with mean score `0.089107`. Tuned RR scores
`0.124592`, MLFQ scores `0.131408`, and SRTF scores `0.174703`. MLFQ loses all
five profiles, has pooled P95 wait `448` versus RR's `446`, and therefore fails
score and fairness gates. All policies pass strict P99 `<10 ms`; MLFQ large
P99 is about `0.150 ms`. Result: keep RR-20-SRTF recommendation and do not add
ML for MLFQ queue or quantum prediction from this evidence.

Run tests with:

```bash
python -m unittest discover -v
```

## Research Interpretation

The experiment must report observed results, including negative or mixed
results. A high classifier accuracy alone does not prove better scheduling.
Primary evidence is adaptive weighted score and paired difference against the
validation-frozen static comparator, plus the per-workload oracle and latency
gate. Do not expand ML when the statistical or latency gate fails. Publish the
negative result or conduct a separately specified objective review.

Suggested paper sections: Methodology, Simulator Design, Workload Generation,
Feature Engineering, Oracle Labeling, Model Training, Experimental Setup,
Results, Discussion, Limitations, and Conclusion.

## Limitations

- Single simulated CPU only
- Static adaptive selection chooses once per workload; the separate dynamic
  experiment can switch at dispatch boundaries
- Offline retraining only
- Synthetic workloads, not kernel traces
- No multicore affinity, deadlines, cache effects, or burst prediction
- Switch cost is simulated only for Priority-RR; it is not kernel timing
- Priority is not part of the weighted objective, so Priority Scheduling may
  rarely be the oracle winner
