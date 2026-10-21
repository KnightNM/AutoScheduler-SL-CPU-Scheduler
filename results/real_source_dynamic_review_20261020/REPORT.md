# Real-source Dynamic ML review

No training or model promotion. Azure-derived simulator evidence, not measured kernel performance.

No local cleaned Linux captures, fitted Linux model or compatible observed-state/finite-action cost rows. Azure saved static-policy costs are not v5 decision-cost targets; saved predicted vectors lack paired actual action costs.

Saved pilot Linux replay summary concerns a different model; source captures/labels are unavailable locally for verification. Not a Dynamic ML v5 result or kernel scheduler validation.

## Existing v5 external evaluation (preserved)

12/17 common completed workloads; 3135 processes; 25132 v5 decisions; 5932 accepted transitions; 19200 rejected-or-held reviews. 8 policy timeouts retained.

## Fresh safety audit

Fresh provenance-disjoint DEVELOPMENT safety audit; not the final holdout. No fresh high-contention provenance groups meet the frozen size/CPU caps; record zero, do not reuse holdout or replace after outcomes.

4/6 common complete workloads; 198 selected processes. Training/validation/test examples: 0/0/0. MAE, RMSE, R²: not recorded, not estimated.

| Policy | Weighted score | Avg waiting ms | Avg response ms | Mean P95 ms | Accepted switches/workload | Routing P99 ms (mean workload P99) |
|---|---:|---:|---:|---:|---:|---:|
| Dynamic v5 | 0.017684 | 188.361111 | 0.000000 | 0.000000 | 4.000000 | 1.923384 |
| Tuned MLFQ | 0.017684 | 188.361111 | 0.000000 | 0.000000 | 0.000000 | Not recorded |
| Guard candidate | 0.017684 | 188.361111 | 0.000000 | 0.000000 | 0.000000 | 3.188675 |

The guard vetoes non-preemptive FCFS/Priority proposals without changing the fitted tree, features, objective, safe boundaries or dwell. The tree never selects RR/Priority-RR, so the candidate collapses to continuous MLFQ; this is verified per process rather than presented as ML superiority.

## Gates and paired uncertainty

{
  "gates": {
    "Weighted score improvement (CI upper < 0)": false,
    "P95 response non-regression (CI upper \u2264 0)": true,
    "Mean starvation non-regression": true,
    "Maximum workload routing P99 < 10 ms": true,
    "Original RR score gate": true,
    "Original RR P95 gate": false,
    "All selected workloads complete": false,
    "Untouched holdout improvement established": false
  },
  "paired": {
    "Tuned MLFQ": {
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
    "Dynamic v5": {
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
    "Round Robin": {
      "weighted_score": {
        "mean": -1.3221508706362517e-05,
        "ci_low": -3.966452611908755e-05,
        "ci_high": 0.0
      },
      "p95_response_ms": {
        "mean": -0.25,
        "ci_low": -0.75,
        "ci_high": 0.0
      },
      "starvation": {
        "mean": 0,
        "ci_low": 0.0,
        "ci_high": 0.0
      }
    }
  }
}

Retain tuned static MLFQ (1,2,4), aging 40. V5 remains experimental. Guard candidate is not promoted.

One tick = 1 ms. Daily wall-clock means are CPU-demand proxies; within-minute arrivals are reconstructed. I/O, actual CPU bursts and OS ready queues are unavailable. Means use identical all-policy-complete workloads; eight older timeouts are retained. Azure scores use five static reference bounds, separate from synthetic scores. No real-kernel or population-wide superiority claim.

Exact frozen metadata-only selection, source groups, exclusions and parameters: `protocol.json`. All attempts and rejection reasons: `audit.json`. Dataset inventory, absent regression metrics and dashboard inputs: `dashboard.json`. Prior Azure holdout groups were neither evaluated nor used for selection. No historical artifacts or research status were modified.

Reproduce in a fresh versioned OUTPUT: `.venv/bin/python -m autoscheduler.real_source_review`; summarize saved outcomes only with `--summarize`.
