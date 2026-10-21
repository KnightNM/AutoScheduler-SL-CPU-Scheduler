# Azure safe-policy headroom: stop before retraining

**No new model, dataset expansion, dashboard change or promotion. Tuned MLFQ remains recommended.**

Analysis uses only existing training/validation rows. Previously examined test rows are excluded from all new prediction and replay analysis. The 73 final-holdout groups are not consumed. Raw Azure records, models, historical reports and dashboard sources remain unchanged.

| Existing development headroom | Count |
|---|---:|
| Decision states / provenance groups | 288 / 24 |
| MLFQ optimal or tied | 285 / 288 |
| Another feasible action has lower objective | 3 |
| Any nonzero action-cost difference (>1e-12) | 7 |
| Benefit clears fixed .005 admission margin | 0 |

Largest feasible benefit: **0.0000781774**, approximately 64.0 times below .005. Largest advantage in any fitted tree leaf: **0.0000022043**. Thus the saved tree cannot admit a learned departure from startup MLFQ under its current margin, even for unseen feature vectors. Its zero switching is primarily an absence of sufficient feasible value, not merely an inaccurate action ranking.

## Existing target already is incremental

Targets are already feasible-action weighted scheduling cost **minus immediate tuned-MLFQ continuation cost**, not absolute whole-workload policy costs. They retain a 20-ms minimum-dwell horizon, safe dispatch return, first-service/arrival restrictions and fixed five-static normalization. Relabeling the same numbers as deltas cannot create headroom. The No Switch/MLFQ outputs are zero in this sample. Features remain observed scheduler history; counterfactual futures are used only for offline targets/analysis.

## Tiny alternatives and response risk

Replayed every one of the 7 nonzero development states, including worse actions; 0 timeouts retained. Each observed feature vector and cost vector is checked against its saved original before reporting outcomes. The exact existing labeler is observed, not reimplemented. Known RR/Priority-RR context-switch charges are included; no new generic policy-setup charge is invented.

| Workload / decision ms | Action | Relative objective | P95 change ms | Worst response change ms | Charged context overhead ms |
|---|---|---:|---:|---:|---:|
| azure-d03-0059 / 1923820 | Round Robin | -0.0000110215 | 0.000 | 0.000 | 0 |
| azure-d03-0059 / 1923820 | Priority RR | -0.0000110215 | 0.000 | 0.000 | 0 |
| azure-d03-0059 / 71602 | Round Robin | -0.0000330644 | 0.000 | 0.000 | 777 |
| azure-d10-0187 / 69313 | Round Robin | -0.0000781774 | 0.000 | 0.000 | 0 |

Full outcomes, including losing Priority-RR alternatives, waiting/response/turnaround, starvation and context switches, are in `counterfactuals.json`. Tied-objective states were not replayed for response differences; they cannot establish strict score superiority. Per-state counterfactuals are not a deployable oracle or a whole-workload adaptive performance claim.

## Regression diagnosis

Only seven states have nonzero feasible cost spreads; zero have admission-sized value. Prediction quality on nonzero (not admission-sized) states is recorded below; no actionable-state metric can be measured from an empty subset. The dummy is the analytical mean of original training costs, with no new fitting. R² is pooled over decision-action pairs, not classification accuracy.

```json
{
  "train": {
    "nonzero_states": 5,
    "metrics_on_nonzero_differences": {
      "existing_tree": {
        "mae": 3.175820274857272e-05,
        "rmse": 6.560202912050295e-05,
        "r_squared": 0.7818343252455079
      },
      "training_mean_dummy": {
        "mae": 7.068089257253064e-05,
        "rmse": 0.00015280705359067473,
        "r_squared": -0.1836919113056772
      }
    },
    "actionable_states": 0,
    "actionable_quality": null,
    "reason": "No state clears the frozen margin"
  },
  "validation": {
    "nonzero_states": 2,
    "metrics_on_nonzero_differences": {
      "existing_tree": {
        "mae": 2.109802470532176e-05,
        "rmse": 3.827985536906404e-05,
        "r_squared": 0.8615557484587314
      },
      "training_mean_dummy": {
        "mae": 6.414148089590393e-05,
        "rmse": 0.00010990115809040954,
        "r_squared": -0.1411398953617382
      }
    },
    "actionable_states": 0,
    "actionable_quality": null,
    "reason": "No state clears the frozen margin"
  }
}
```

Adding a small averaging forest or a larger tree cannot create true benefit exceeding the observed target range. Negative validation R² remains a modeling weakness, but fixing it would not unlock a safe switch under this margin. The old v5 Priority gains involve a prohibited non-preemptive action and previously demonstrated response risk; they are not eligible headroom.

## Verdict and limits

No useful safe switching behavior or superiority over MLFQ is demonstrated. Stop before Phases 2–5: do not enlarge the dataset, change thresholds, fit another model or revisit test outcomes merely to force transitions. Preserve the existing dashboard exactly. The known dataset is capped/mostly low contention, so absence of headroom here is not proof that all 510 Azure workloads lack it. Larger queues and high-contention source groups would require a separately justified, frozen feasibility study. Azure wall-clock CPU-demand proxies and reconstructed arrivals do not establish Linux scheduler behavior.

Reproduce in a fresh OUTPUT: `.venv/bin/python -m autoscheduler.azure_headroom`. Focused tests, unchanged-hash checks and dashboard build are recorded in `verification.json`. No push or merge.
