"""Development-only offline replay labels for the real-trace prototype."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Iterable

from autoscheduler.evaluation import DEPLOYABLE_ALGORITHMS, compare_algorithms, score_results
from autoscheduler.fairness import FAIRNESS_FIELDS, aggregate_fairness
from autoscheduler.real_features import FEATURE_NAMES, IDENTIFIER_NAMES, extract_feature_rows
from autoscheduler.real_replay import build_replay_workload


LABEL_PROVENANCE = "pilot_offline_replay_development_only"
SYNTHETIC_LABEL_PROVENANCE = "synthetic_development_only"


def _results(processes):
    return compare_algorithms(processes, algorithms=DEPLOYABLE_ALGORITHMS)


def build_development_action_rows(
    traces: Iterable[dict[str, Any]], config: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Attach replay-only policy costs to observed snapshots; never treat them as kernel evidence."""
    traces = list(traces)
    sources = {trace["metadata"].get("source") for trace in traces}
    if sources == {"synthetic"}:
        provenance = SYNTHETIC_LABEL_PROVENANCE
    elif "synthetic" in sources:
        raise ValueError("synthetic and captured traces cannot share one development dataset")
    else:
        provenance = LABEL_PROVENANCE
    rows, accepted, rejected = [], 0, []
    control = config["control"]
    for trace in traces:
        metadata = trace["metadata"]
        if not metadata.get("anonymized"):
            raise ValueError(f"{metadata['trace_id']}: real dataset input must be anonymized")
        try:
            replay = build_replay_workload(trace)
        except ValueError as error:
            rejected.append({"trace_id": metadata["trace_id"], "reason": str(error)})
            continue
        results = _results(replay.processes)
        scores = score_results(results)
        fairness = {action: aggregate_fairness(result.process_metrics) for action, result in results.items()}
        snapshots = extract_feature_rows(
            [trace], control["initial_observation_ms"], control["feature_window_ms"],
            control["decision_interval_ms"],
        )
        accepted += 1
        for snapshot in snapshots:
            for action, cost in scores.items():
                rows.append({
                    **snapshot,
                    "action": action,
                    "policy_cost": cost,
                    **fairness[action],
                    "source_result": f"{metadata['trace_id']}:{action}",
                    "label_provenance": provenance,
                })
    return rows, {
        "label_provenance": provenance,
        "accepted_traces": accepted,
        "rejected_traces": rejected,
        "rows": len(rows),
    }


def write_development_action_rows(rows: Iterable[dict[str, Any]], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=[*IDENTIFIER_NAMES, *FEATURE_NAMES, "action", "policy_cost", *FAIRNESS_FIELDS, "source_result", "label_provenance"])
        writer.writeheader()
        writer.writerows(rows)
