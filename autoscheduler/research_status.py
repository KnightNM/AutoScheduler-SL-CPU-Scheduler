"""Generate a read-only integration catalog from research reports, never claims."""
import argparse
import hashlib
import json
from pathlib import Path
from statistics import mean

from autoscheduler.evaluation import ALGORITHMS, DEPLOYABLE_ALGORITHMS, SCORE_WEIGHTS


METRICS = {
    "weighted_score": ("mean_score", "dimensionless", "mean over workloads; lower is better"),
    "p95_response": ("mean_p95_response", "simulator_tick", "mean of workload first-response P95s"),
    "worst_first_response": ("max_first_response", "simulator_tick", "maximum over all processes"),
    "starvation": ("mean_starvation", "processes_per_workload", "mean frozen fairness starvation count"),
    "switches": ("mean_switches", "switches_per_workload", "mean accepted policy transitions"),
    "decision_p99": ("pooled_routing_p99_ms", "millisecond", "pooled routing decision P99; simulator controller only"),
    "max_workload_decision_p99": ("max_workload_decision_p99_ms", "millisecond", "maximum workload routing P99; latency gate input"),
}


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_status(root: Path):
    """Project-relative paths, per-dataset metrics, null for unmeasured values."""
    models, evaluations, latest = [], [], None
    reports = sorted(root.glob("results/dynamic_v*/research_summary.json"),
                     key=lambda p: int(p.parent.name.split("_")[1][1:]))
    for source in reports:
        summary = json.loads(source.read_text())
        version = source.parent.name.split("_")[1]
        number = int(version[1:])
        artifact_root = root / "artifacts" / source.parent.name
        for family, expected_hash in summary.get("model_sha256", {}).items():
            path = artifact_root / family / "model.joblib"
            if number <= 3:
                path = artifact_root / "candidates" / family / "model.joblib"
            available = path.is_file()
            digest = _sha(path) if available else None
            models.append({"id": f"dynamic_{version}_{family}", "version": version, "family": family,
                "status": "historical" if number < 5 else "experimental",
                "scope": summary["status"], "approved": False,
                "requires_archived_runtime": number < 5,
                "development_audit_accepted": summary.get("acceptance", {}).get(family),
                "artifact": {"path": str(path.relative_to(root)), "available": available,
                             "sha256": digest, "validated": available and digest == expected_hash},
                "report": str(source.parent.relative_to(root) / "REPORT.md"),
                "summary": str(source.relative_to(root)), "summary_sha256": _sha(source)})
        # Earlier report schemas remain linked rather than being guessed into this schema.
        if number >= 5:
            latest = summary
            audit = summary["audit"]
            evaluations.append({"id": source.parent.name, "scope": summary["status"],
                "source": str(source.relative_to(root)), "source_sha256": _sha(source),
                "audit_seed": summary["protocol"]["seeds"]["audit"],
                "workloads": summary["protocol"]["traces"]["audit"],
                "primary_static_comparator": summary["primary_baseline"],
                "tuned_static_parameters": summary["tuned_parameters"],
                "policy_model_ids": {name: f"dynamic_{version}_{name}" if name in ("classifier", "policy_cost")
                    else f"dynamic_v{name.split()[-1][1:]}_policy_cost" if name.startswith("Dynamic v") else None
                    for name in audit if name != "MLFQ control"},
                "metrics": {name: {key: values.get(field) for key, (field, _, _) in METRICS.items()}
                            for name, values in audit.items() if name != "MLFQ control"},
                "safety_gates": {name: values["gates"] for name, values in audit.items() if "gates" in values},
                "paired_confidence_intervals": str(source.parent.relative_to(root) / "audit/summary.json"),
                "development_selected": summary.get("development_selected"),
                "accepted_after_audit": summary.get("accepted_after_audit")})
    if latest is None:
        raise ValueError("v5 or later validated research summary is required")
    algorithms = [{"name": name, "eligibility": "observed_state_eligible" if name in DEPLOYABLE_ALGORITHMS else "oracle_only",
                   "parameters": parameters} for name, (_, parameters) in {**ALGORITHMS, **DEPLOYABLE_ALGORITHMS}.items()]
    algorithms.append({"name": "RR20-SRTF", "eligibility": "oracle_only",
                       "parameters": {"rr_quantum": 1, "switch_tick": 20}})
    chosen = latest.get("accepted_after_audit")
    research_version = evaluations[-1]["id"].split("_")[1] if chosen else "v5"
    checkpoint_path = reports[-1].parent / "CHECKPOINT.json"
    checkpoint = json.loads(checkpoint_path.read_text()) if checkpoint_path.exists() else {}
    sensitivity_path = reports[-1].parent / "sensitivity.json"
    if sensitivity_path.exists():
        sensitivity = json.loads(sensitivity_path.read_text())
        groups = {name: [r for r in sensitivity["rows"] if r["policy"] == name]
                  for name in dict.fromkeys(r["policy"] for r in sensitivity["rows"])}
        evaluations.append({"id": "v6_fixed_v5_static_sensitivity", "scope": "POST_AUDIT_EXPLANATION_ONLY_NOT_SELECTION",
            "source": str(sensitivity_path.relative_to(root)), "source_sha256": _sha(sensitivity_path),
            "audit_seed": 10603, "workloads": len(next(iter(groups.values()))),
            "metrics": {name: {"weighted_score": mean(r["score"] for r in rows),
                "p95_response": mean(r["p95_response"] for r in rows),
                "worst_first_response": max(r["worst_response"] for r in rows),
                "starvation": mean(r["starvation"] for r in rows),
                "switches": mean(r["switches"] for r in rows),
                "decision_p99": sensitivity["ablation_pooled_p99_ms"] if name == "V5 plus v6 guard" else None,
                "max_workload_decision_p99": max(r["decision_p99_ms"] for r in rows)
                    if name == "V5 plus v6 guard" else None} for name, rows in groups.items()},
            "safety_gates": {name: data["against_frozen_v5_static_gates"]
                             for name, data in sensitivity["comparisons"].items()},
            "primary_static_comparator": "Frozen v5 Tuned MLFQ",
            "tuned_static_parameters": checkpoint.get("recommended_static", {}).get("parameters"),
            "policy_model_ids": {name: None for name in groups},
            "note": "Disposable guard-only intervention has no trained or approved deployment artifact."})
    recommendation = checkpoint.get("recommended_static", {"name": latest["primary_baseline"],
        "parameters": latest["tuned_parameters"], "scope": "synthetic_development_simulator; no real-kernel performance claim"})
    return {"schema_version": 1, "synthetic_tuning": "closed", "next_phase": "interactive_dashboard",
        "approved_ml_models": [], "promotion": False,
        "approval_blockers": ["Synthetic results cannot select the final real-data model; locked real-trace gates remain required."],
        "research_candidate": checkpoint.get("research_candidate", f"dynamic_{research_version}_{chosen or 'policy_cost'}"),
        "recommended_static": recommendation,
        "checkpoint": {"path": str(checkpoint_path.relative_to(root)), "sha256": _sha(checkpoint_path),
                       "decision": checkpoint} if checkpoint else None,
        "algorithms": algorithms, "models": models, "score_weights": SCORE_WEIGHTS,
        "metric_definitions": {key: {"unit": unit, "aggregation": aggregation} for key, (_, unit, aggregation) in METRICS.items()},
        "evaluations": evaluations,
        "loading_contract": "Only load validated artifacts using their saved configuration and schema. Never substitute controller settings silently.",
        "real_data_contract": "configs/real_desktop_ml.json"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("configs/research_status.json"))
    args = parser.parse_args()
    status = build_status(Path.cwd())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(status, indent=2) + "\n")


if __name__ == "__main__":
    main()
