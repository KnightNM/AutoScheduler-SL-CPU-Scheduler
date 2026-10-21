# Azure-adapted policy-cost tree: one controlled development experiment

**Reconstructed real-source workload simulations, not Linux kernel measurements. No model promoted.**

## Protocol and data

Microsoft Azure Functions 2019 revision 2, CC-BY; Mohammad Shahrad et al., “Serverless in the Wild,” ATC 2020. Original cleaned input: 510 workloads/520,408 reconstructed jobs. No source record, scheduler parameter, objective weight or historical result changed. One tick = 1 ms. Daily mean wall-clock durations remain CPU-demand proxies; within-minute arrivals are reconstructed.

Seed 20261022. Select complete workloads by metadata, before outcomes: 5–100 processes; low/mixed-low total proxy work <=20,000 ms, moderate <=100,000 ms, high <=200,000 ms. One workload per connected owner/app/function component across all days/hours/snapshots. Selected 30 groups: 24 low, 2 mixed-low, 4 moderate. No high-contention group satisfies caps. The 73 separately reserved groups are disjoint from every selected source and never evaluated. This cap-limited experiment cannot establish broad Azure or high-contention generalization.

Descriptive metadata coverage (not additional selection/tuning): {"cohorts": {"retained_control": 30}, "heterogeneous_proxy_bursts": 7, "sustained_span_proxy": 27, "interarrival_cv_at_least_one": 8, "high_contention": 0, "scope": "Descriptive metadata coverage after frozen selection; reconstructed arrival shape, not observed OS bursts; no outcome-based resampling"}.

Protocol and split IDs were saved before labeling/fitting. Three representative reference+finite-label benchmarks each passed the fixed 10-second budget (`feasibility.json`). Labeling has a predeclared 60-second whole-workload cap; every timeout/empty workload remains in `label_outcomes.json`, with no replacement. Evaluation retains every 20-second per-policy timeout and never renormalizes missing references.

## Targets, safety and model selection

Nineteen inputs come from existing observed-state extraction at actual legal dispatch boundaries. Each MLFQ or safeguarded preemptive-exploration trajectory contributes up to six uniform reservoir states. Bounded sampling avoids copying every historical timeline and does not change trajectory policy or timestamps. Labels use the existing feasible-action counterfactual: hold through minimum dwell until the next safe review, then tuned MLFQ to completion; score differences use the same five frozen eligible-static bounds. Future simulator outcomes belong only to targets; no future arrivals, remaining burst or oracle features enter inference.

Eligible learned actions: **No Switch, MLFQ, RR2, Priority-RR2**. Non-preemptive FCFS/Priority departures are excluded before argmin, rather than changing their scheduler semantics. Fixed static FCFS/Priority remain comparators. Confidence, .005 benefit margin, first-service/arrival protection, fallback, 20-ms dwell and safe return logic remain unchanged. Priority-RR retains its inherited 1-ms context-switch cost; other policies retain zero. The tiny deterministic test reproduces the original Priority response of 60 ticks and verifies a preemptive action limits that example to <=2.

Two trees only: depth 3 or 5, leaf 5, seed fixed. Fit training groups only. Choose by validation safety eligibility, then realized scheduling score; no classification-accuracy selection. No forest, refit, test-driven retuning or final-holdout use. `frozen_candidate.json` and model hash precede test prediction/scoring.

Frozen candidate: **Azure tree depth 3**. Development-selected primary static: **Round Robin**.

## Prediction metrics

Dimensionless weighted-score delta versus tuned MLFQ continuation; MAE/RMSE over four decision-action cost outputs, R² pooled over decision-action pairs. R² is not classification accuracy. Constant targets yield undefined R², never an invented perfect value. Two zero/reference output heads can affect pooled R²; compare the mean-cost dummy and realized schedules rather than relying on R² alone.

| Split | Selected groups / labeled groups | Processes selected | Decision rows | MAE | RMSE | R² | Mean-cost dummy MAE / RMSE / R² |
|---|---:|---:|---:|---:|---:|---:|---|
| train | 18 / 18 | 603 | 216 | 0.00000107 | 0.00001327 | 0.68308657 | 0.00000313 / 0.00002343 / 0.01141256 |
| validation | 6 / 6 | 150 | 72 | 0.00000342 | 0.00002698 | -1.07123306 | 0.00000327 / 0.00001855 / 0.02101791 |
| test | 6 / 6 | 115 | 72 | 0.00000353 | 0.00005603 | 0.37659292 | 0.00000587 / 0.00007079 / 0.00488705 |

Strict/tie-aware action agreement and a fixed No Switch reference are in `results.json`; these are reference-action agreement, not classifier accuracy. All observed features/actual costs are saved locally in `artifacts/dynamic_azure_adapted_20261020/decision_costs.json`; test numerical predictions are saved separately. Grouped rows are correlated; the group—not individual rows—is the independent split unit.

Reference actions: {'No Switch': 356, 'Round Robin': 4}. Largest feasible switch benefit among all 360 sampled states: 0.0000781774, versus frozen margin .005; no row clears the margin. The frozen tree’s largest leaf-predicted advantage is 0.0000022043, also below the margin. Consequently this tree cannot accept a learned departure with the existing safeguards. Tiny absolute errors are partly a consequence of nearly-zero targets, not proof of useful adaptation. A larger averaging forest cannot fix the observed absence of sufficiently valuable eligible actions. The negative validation R² and dummy baseline are retained, not hidden.

Internal test: 6 groups, of which 2 were previously inspected. They are separate from this fit’s train/validation groups, but the full set is not an untouched independent test.

P95 improvements versus v5 occur in: [{'workload_id': 'azure-d05-0094', 'previous_source_group_seen': True}]. The observed improvement is confined to a previously inspected source; it is not new independent response-tail evidence.

## Identical internal-test scheduling workloads

6/6 workloads completed every policy; 115 processes in that common subset. 0 policy timeouts retained. The following means use only common complete inputs; missing coverage is not success.

| Policy | Score | Waiting ms | Response ms | P95 ms | Turnaround ms | Utilization | Jobs/ms | Starvation | Context switches | Accepted / nonaccepted reviews |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| FCFS | 0.04166667 | 9.04716981 | 9.04716981 | 86.06666667 | 1005.30431267 | 0.00882028 | 0.00000702 | 0.00000000 | 18.16666667 | 0.00000000 / 0.00000000 |
| Round Robin | 0.02757753 | 18.09748428 | 0.01257862 | 0.16666667 | 1014.35462713 | 0.00882028 | 0.00000702 | 0.00000000 | 497.83333333 | 0.00000000 / 0.00000000 |
| Priority | 0.04166667 | 9.04716981 | 9.04716981 | 86.06666667 | 1005.30431267 | 0.00882028 | 0.00000702 | 0.00000000 | 18.16666667 | 0.00000000 / 0.00000000 |
| Priority RR | 0.95910092 | 37.20818733 | 0.92202381 | 1.00000000 | 1033.46533019 | 0.00882027 | 0.00000702 | 0.00000000 | 499.16666667 | 0.00000000 / 0.00000000 |
| MLFQ | 0.02805508 | 18.27358491 | 0.00000000 | 0.00000000 | 1014.53072776 | 0.00882028 | 0.00000702 | 0.00000000 | 140.83333333 | 0.00000000 / 0.00000000 |
| Tuned MLFQ | 0.02752916 | 18.10062893 | 0.00000000 | 0.00000000 | 1014.35777179 | 0.00882028 | 0.00000702 | 0.00000000 | 258.50000000 | 0.00000000 / 0.00000000 |
| Azure tree | 0.02752916 | 18.10062893 | 0.00000000 | 0.00000000 | 1014.35777179 | 0.00882028 | 0.00000702 | 0.00000000 | 258.50000000 | 0.00000000 / 1889.50000000 |
| Dynamic v5 | 0.04166667 | 9.04716981 | 9.04716981 | 86.06666667 | 1005.30431267 | 0.00882028 | 0.00000702 | 0.00000000 | 18.16666667 | 31.66666667 / 141.00000000 |

Context switches are PID transitions; accepted policy transitions are distinct. Nonaccepted reviews include same-policy holds and blocked proposals; reasons are saved per workload. Routing P99 includes observed feature/model/guard work; static inference latency is unmeasured. No generic adaptive reconfiguration charge is added.

Exact test transition totals (same-policy holds separated from rejected switching reviews): {"Azure tree": {"accepted_switches": 0, "rejected_switch_reviews": 18, "same_policy_holds": 11319}, "Dynamic v5": {"accepted_switches": 190, "rejected_switch_reviews": 846, "same_policy_holds": 0}}.

Pure batch-one model inference: 72 saved test states; mean 0.050504 ms, P99 0.126819 ms. This one-pass microbenchmark is separate from routing P99. Python inference time does not advance simulated workload time; it is not charged into scheduling throughput/utilization and is not Linux controller timing.

## Frozen gates and uncertainty

Paired workload percentile bootstrap, 10,000 draws, seed 2027, one workload per provenance group. Tiny, capped, previously examined development sources make intervals exploratory, not final generalization evidence.

```json
{
  "versus_primary": {
    "eligible": false,
    "gates": {
      "score": false,
      "p95": true,
      "starvation": true,
      "latency": true,
      "coverage": true,
      "original_rr_score": true,
      "original_rr_p95": false
    },
    "pairs": 6,
    "differences": {
      "weighted_score": {
        "mean": -4.8368657110220425e-05,
        "ci_low": -0.00014510597133066128,
        "ci_high": 0.0
      },
      "p95_response_ms": {
        "mean": -0.16666666666666666,
        "ci_low": -0.5,
        "ci_high": 0.0
      },
      "starvation": {
        "mean": 0,
        "ci_low": 0.0,
        "ci_high": 0.0
      }
    },
    "max_workload_p99_ms": 2.9339229500000026,
    "mean_score": 0.027529164276152224,
    "comparator": "Round Robin"
  },
  "versus_tuned": {
    "eligible": false,
    "gates": {
      "score": false,
      "p95": true,
      "starvation": true,
      "latency": true,
      "coverage": true,
      "original_rr_score": true,
      "original_rr_p95": false
    },
    "pairs": 6,
    "differences": {
      "weighted_score": {
        "mean": 0.0,
        "ci_low": 0.0,
        "ci_high": 0.0
      },
      "p95_response_ms": {
        "mean": 0.0,
        "ci_low": 0.0,
        "ci_high": 0.0
      },
      "starvation": {
        "mean": 0,
        "ci_low": 0.0,
        "ci_high": 0.0
      }
    },
    "max_workload_p99_ms": 2.9339229500000026,
    "mean_score": 0.027529164276152224,
    "comparator": "Tuned MLFQ"
  }
}
```

Keep tuned static MLFQ (1,2,4), aging 40. Preserve v5 as historical experimental baseline; do not promote this Azure candidate.

Metadata-capped sample: no high-contention workload fits caps; no measured I/O or OS ready queues. Wall-clock duration proxies are not observed CPU bursts. No Linux-kernel performance claim.

Model: `artifacts/dynamic_azure_adapted_20261020/model.joblib`, SHA256 `c5b49844df05be069ed9daa718e5d22eb423c63aeede339d9ddc3172aaa31fc8`. All 213 pre-existing protected report/model/data/configuration hashes match. Verification is saved separately in `verification.json`. No push/merge.

Reproduce only with fresh versioned OUTPUT/ARTIFACTS paths: `.venv/bin/python -m autoscheduler.azure_adaptation`; read saved results with `.venv/bin/python -m autoscheduler.azure_adaptation_report`. Completed experiments refuse overwrite.
