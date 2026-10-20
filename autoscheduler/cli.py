"""Command-line interface for training and evaluating AutoScheduler."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from autoscheduler.adaptive import run_adaptive
from autoscheduler.benefit import (
    BenefitConfig,
    evaluate_benefit,
    load_benefit_model,
    run_benefit_latency,
    save_benefit_evaluation,
    save_benefit_latency,
    train_benefit,
)
from autoscheduler.dataset import build_dataset, save_dataset
from autoscheduler.dynamic import (
    DYNAMIC_FEATURE_NAMES,
    DynamicRouterConfig,
    evaluate_dynamic,
    save_dynamic_evaluation,
    tune_dynamic_config,
)
from autoscheduler.evaluation import compare_algorithms, score_results
from autoscheduler.experiments import evaluate_model, save_evaluation
from autoscheduler.latency import run_latency_experiment, save_latency
from autoscheduler.model import load_model, load_model_metadata, train_model
from autoscheduler.mlfq_experiment import (
    evaluate_mlfq,
    finalize_mlfq_summary,
    run_mlfq_latency,
    save_mlfq_evaluation,
    save_mlfq_latency,
)
from autoscheduler.priority_rr import tune_priority_rr
from autoscheduler.workloads import PROFILES, generate_workload


DEFAULT_MODEL = Path("artifacts/model.joblib")
DEFAULT_DYNAMIC_MODEL = Path("artifacts/dynamic_v3/model.joblib")
DEFAULT_BENEFIT_ROOT = Path("results/rr_srtf_benefit")
DEFAULT_MLFQ_ROOT = Path("results/mlfq_baseline")


def _real_config(arguments) -> None:
    from autoscheduler.real_config import config_hash, load_real_config

    config = load_real_config(arguments.config)
    policies = ", ".join(policy["name"] for policy in config["policies"]["deployable"])
    print(f"Contract valid: {config['experiment_id']}")
    print(f"SHA256: {config_hash(config)}")
    print(f"Deployable policies: {policies}")


def _real_trace_import(arguments) -> None:
    from autoscheduler.linux_trace import import_trace_files

    trace = import_trace_files(
        arguments.report, arguments.metadata, arguments.output, arguments.trace_id
    )
    print(f"Trace: {trace['metadata']['trace_id']}")
    print(f"Processes: {len(trace['processes'])}")
    print(f"Events: {len(trace['events'])}")
    print(f"Output: {arguments.output}")


def _real_trace_validate(arguments) -> None:
    from autoscheduler.real_traces import read_traces

    traces = read_traces(arguments.path)
    print(f"Valid traces: {len(traces)}")
    print(f"Processes: {sum(len(trace['processes']) for trace in traces)}")
    print(f"Events: {sum(len(trace['events']) for trace in traces)}")


def _real_trace_clean(arguments) -> None:
    from autoscheduler.real_clean import clean_trace_files

    traces = clean_trace_files(arguments.paths, arguments.output, arguments.capture_session)
    print(f"Cleaned traces: {len(traces)}")
    print(f"Processes: {sum(len(trace['processes']) for trace in traces)}")
    print(f"Output: {arguments.output}")


def _real_features(arguments) -> None:
    from autoscheduler.real_config import load_real_config
    from autoscheduler.real_features import FEATURE_NAMES, extract_feature_rows, write_feature_rows
    from autoscheduler.real_traces import read_traces

    config = load_real_config(arguments.config)
    if tuple(config["features"]["allowed"]) != FEATURE_NAMES:
        raise SystemExit("configured real-trace features do not match extractor")
    control = config["control"]
    rows = extract_feature_rows(
        [trace for path in arguments.paths for trace in read_traces(path)],
        control["initial_observation_ms"],
        control["feature_window_ms"],
        control["decision_interval_ms"],
    )
    write_feature_rows(rows, arguments.output)
    print(f"Feature rows: {len(rows)}")
    print(f"Output: {arguments.output}")


def _real_split(arguments) -> None:
    from autoscheduler.real_config import load_real_config
    from autoscheduler.real_split import read_feature_rows, write_split_manifest

    config = load_real_config(arguments.config)
    dataset = config["dataset"]
    manifest = write_split_manifest(
        read_feature_rows(arguments.path), arguments.output, dataset["split"],
        tuple(dataset["group_by"]), config["seeds"]["split"],
    )
    for name in ("train", "validation", "test"):
        print(f"{name.title()} traces: {len(manifest['trace_ids'][name])}")
    print(f"Output: {arguments.output}")


def _real_dataset(arguments) -> None:
    from autoscheduler.real_config import load_real_config
    from autoscheduler.real_dataset import build_development_action_rows, write_development_action_rows
    from autoscheduler.real_traces import read_traces

    rows, summary = build_development_action_rows(
        [trace for path in arguments.paths for trace in read_traces(path)], load_real_config(arguments.config)
    )
    write_development_action_rows(rows, arguments.output)
    print(f"Action rows: {summary['rows']}")
    print(f"Accepted traces: {summary['accepted_traces']}")
    print(f"Label provenance: {summary['label_provenance']}")
    print(f"Output: {arguments.output}")


def _real_synthetic_capture(arguments) -> None:
    from autoscheduler.real_synthetic import write_synthetic_traces

    traces = write_synthetic_traces(arguments.output, arguments.repetitions, arguments.seed)
    print("Status: SYNTHETIC_DEVELOPMENT_ONLY")
    print(f"Traces: {len(traces)}")
    print(f"Output: {arguments.output}")


def _model_bakeoff(arguments) -> None:
    from autoscheduler.real_bakeoff import run_prototype_bakeoff
    from autoscheduler.real_config import load_real_config
    from autoscheduler.real_split import read_feature_rows
    from autoscheduler.real_traces import read_traces

    source = Path(arguments.path)
    cleaned = source.with_name("cleaned.jsonl")
    traces = read_traces(cleaned) if cleaned.exists() else None
    report = run_prototype_bakeoff(read_feature_rows(arguments.path), load_real_config(arguments.config), arguments.output, traces)
    selected = report["bakeoff"]["selected"]
    print(f"Label provenance: {report['label_provenance']}")
    print(f"Selected model: {selected['family']}")
    print(f"Validation realized cost: {selected['validation_score']:.6f}")
    print(f"Locked test realized cost: {selected['test_score']:.6f}")
    print(f"Gate status: {report['gates']['status']}")
    print(f"Fixed comparator: {report['gates']['fixed_comparator']}")
    print(f"Results: {arguments.output}")


def _dynamic_demo(arguments) -> None:
    from autoscheduler.dynamic_demo import run

    run(
        Path(arguments.output), Path(arguments.artifacts), arguments.train_traces,
        arguments.validation_traces, arguments.train_seed, arguments.validation_seed,
        arguments.demo_seed, arguments.config,
    )


def _real_replay_build(arguments) -> None:
    from autoscheduler.real_replay import write_replay_manifest
    from autoscheduler.real_traces import read_traces

    manifest = write_replay_manifest(
        [trace for path in arguments.paths for trace in read_traces(path)], arguments.output
    )
    summary = manifest["summary"]
    print(f"Replay traces: {len(manifest['traces'])}")
    print(f"Accepted traces: {summary['accepted_traces']}")
    print(f"Accepted processes: {summary['accepted_processes']}")
    print(f"Rejected processes: {summary['rejected_processes']}")
    print(f"Output: {arguments.output}")


def _model(path: str):
    if not Path(path).exists():
        raise SystemExit(f"Model not found: {path}. Run `python main.py train` first.")
    return load_model(path)


def _train(arguments) -> None:
    tuning = tune_priority_rr(arguments.samples_per_profile, arguments.seed)
    priority_rr_config = {
        key: tuning["selected"][key]
        for key in ("quantum", "aging_interval", "context_switch_cost")
    }
    rows = build_dataset(arguments.samples_per_profile, arguments.seed, priority_rr_config)
    save_dataset(rows, arguments.dataset)
    report = train_model(rows, arguments.model, arguments.seed, priority_rr_config)
    report["priority_rr_tuning"] = tuning
    report_path = Path(arguments.model).with_suffix(".json")
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Training rows: {report['rows']}")
    print(f"Validation accuracy: {report['validation_accuracy']:.3f}")
    print(f"Validation regret: {report['validation_mean_regret']:.4f}")
    print(f"Test accuracy: {report['test_accuracy']:.3f}")
    print(f"Test regret: {report['test_mean_regret']:.4f}")
    print(f"Model: {arguments.model}")


def _compare(arguments) -> None:
    workload = generate_workload(arguments.profile, arguments.seed, arguments.process_count)
    model = _model(arguments.model)
    config = load_model_metadata(arguments.model).get("priority_rr_config")
    results = compare_algorithms(workload.processes, config)
    scores = score_results(results)
    adaptive = run_adaptive(workload.processes, model, config)

    print(f"Workload: {workload.profile} | seed={workload.seed} | processes={len(workload.processes)}")
    print("Features:")
    for name, value in adaptive.features.items():
        print(f"  {name}: {value:.4f}")
    print("\nAlgorithm       Wait    Response  Turnaround  CPU utilization  Throughput  Score")
    for name, result in results.items():
        print(
            f"{name:<15} {result.avg_waiting_time:>7.2f} {result.avg_response_time:>9.2f} "
            f"{result.avg_turnaround_time:>11.2f} {result.cpu_utilization:>16.3f} "
            f"{result.throughput:>11.3f} {scores[name]:>6.3f}"
        )
    print(f"\nAdaptive selected: {adaptive.selected_algorithm} ({adaptive.inference_ms:.4f} ms)")
    print("Timeline:", " | ".join(f"{pid}[{start}-{end}]" for pid, start, end in adaptive.simulation.timeline))


def _evaluate(arguments) -> None:
    tuning = None
    metadata = load_model_metadata(arguments.model)
    priority_rr_config = metadata.get("priority_rr_config")
    if arguments.tune_priority_rr:
        if priority_rr_config:
            raise SystemExit("Model already contains frozen Priority-RR configuration.")
        tuning = tune_priority_rr(arguments.tune_samples_per_profile, arguments.tune_seed)
        priority_rr_config = {
            key: tuning["selected"][key]
            for key in ("quantum", "aging_interval", "context_switch_cost")
        }
    rows, summary = evaluate_model(
        _model(arguments.model),
        arguments.samples_per_profile,
        arguments.seed,
        priority_rr_config,
        metadata.get("static_baseline"),
    )
    if tuning:
        summary["priority_rr_tuning"] = tuning
    save_evaluation(rows, summary, arguments.output)
    print(f"Samples: {summary['samples']}")
    print(f"Accuracy: {summary['accuracy']:.3f}")
    print(f"Mean regret: {summary['mean_regret']:.4f}")
    print(f"Best static: {summary['best_static_algorithm']}")
    print(f"Adaptive score: {summary['mean_adaptive_score']:.4f}")
    print(f"Constant SJF score: {summary['constant_sjf']['mean_score']:.4f}")
    print(f"Oracle score: {summary['mean_oracle_score']:.4f}")
    print(f"Adaptive beats best static: {summary['adaptive_beats_best_static']}")
    print(f"Adaptive beats SJF: {summary['adaptive_beats_sjf']}")
    print(f"Statistically beats static: {summary['adaptive_statistically_beats_static']}")
    print(f"Eligible for next adaptive phase: {summary['eligible_for_next_adaptive_phase']}")
    print(f"Priority RR config: {summary['priority_rr_config']}")
    print(f"Priority RR beats SJF: {summary['priority_rr_beats_sjf']}")
    print(f"Results: {arguments.output}")


def _latency(arguments) -> None:
    score_path = Path(arguments.score_summary)
    if not score_path.exists():
        raise SystemExit(f"Score summary not found: {score_path}. Run `python main.py evaluate` first.")
    score_summary = json.loads(score_path.read_text(encoding="utf-8"))
    rows, summary = run_latency_experiment(
        _model(arguments.model), score_summary, arguments.samples_per_profile, arguments.seed, arguments.warmups
    )
    save_latency(rows, summary, arguments.output)
    print(f"P99 gate: < {summary['gate_p99_ms']:.0f} ms")
    print(f"Best static passing gate: {summary['best_static_policy']}")
    print(f"Adaptive beats static: {summary['adaptive_beats_static']}")
    print(f"Recommended policy: {summary['recommended_policy']}")
    print(f"Results: {arguments.output}")


def _dynamic_train(arguments) -> None:
    from autoscheduler.dynamic_training import build_training_data, prepare_validation, validation_metrics

    if arguments.tune_router:
        tuning = tune_dynamic_config(arguments.tuning_traces, arguments.seed,
                                     policy_track=arguments.policy_track, model_kind=arguments.model_kind,
                                     initial_policy=arguments.initial_policy,
                                     fallback_policy=None if arguments.fallback_policy == "hold" else arguments.fallback_policy)
    else:
        explicit = DynamicRouterConfig(arguments.epoch_ticks, arguments.dwell_epochs, arguments.confidence,
                                       arguments.policy_track, arguments.initial_policy,
                                       None if arguments.fallback_policy == "hold" else arguments.fallback_policy)
        tuning = {"method": "explicit_configuration", "selected": explicit.__dict__}
    config = DynamicRouterConfig(**tuning["selected"])
    development = arguments.workload_suite == "development"
    rows, occupancy = build_training_data(arguments.traces, arguments.seed, config,
                                          Path(arguments.model).with_suffix(".split.json"), development=development)
    cases, validation = prepare_validation(arguments.tuning_traces, arguments.seed + 1_000_000, config,
                                           development=development)
    save_dataset(rows, arguments.dataset)
    report = train_model(
        rows, arguments.model, arguments.seed, feature_names=DYNAMIC_FEATURE_NAMES,
        metadata={"dynamic_config": config.__dict__, "dynamic_tuning": tuning,
                  "static_baseline": validation["static_baseline"]},
        group_key="seed",
        model_kind=arguments.model_kind,
        scheduler_validation=lambda model: validation_metrics(model, cases, config),
    )
    report["dynamic_tuning"] = tuning
    report["occupancy"] = occupancy
    report["whole_workload_validation"] = validation
    Path(arguments.model).with_suffix(".json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Dynamic rows: {report['rows']}")
    print(f"Router config: {config}")
    print(f"Model: {arguments.model}")


def _dynamic_evaluate(arguments) -> None:
    metadata = load_model_metadata(arguments.model)
    if "dynamic_config" not in metadata:
        raise ValueError("saved model lacks dynamic configuration; retrain with dynamic-train")
    config = DynamicRouterConfig(**metadata["dynamic_config"])
    rr_config = metadata.get("priority_rr_config")
    model = load_model(arguments.model, DYNAMIC_FEATURE_NAMES, expected_dynamic_config=config, expected_priority_rr_config=rr_config)
    rows, summary = evaluate_dynamic(model, arguments.traces, arguments.seed, config, rr_config,
                                     frozen_static_baseline=metadata["static_baseline"])
    save_dynamic_evaluation(rows, summary, arguments.output)
    print(f"P95 response gate: {summary['p95_response_gate']}")
    print(f"Weighted score gate: {summary['weighted_score_gate']}")
    print(f"Latency gate: {summary['latency_gate']}")
    print(f"Eligible: {summary['eligible']}")
    print(f"Results: {arguments.output}")


def _benefit_train(arguments) -> None:
    report = train_benefit(
        arguments.samples_per_profile, arguments.seed, arguments.model, arguments.dataset
    )
    print(f"Tuned RR quantum: {report['config']['rr_quantum']}")
    print(f"Observation window: {report['config']['observation_ticks']}")
    print(f"Switch margin: {report['config']['margin']}")
    print(f"Internal test score: {report['internal_test_mean_score']:.6f}")
    print(f"Model: {arguments.model}")


def _benefit_evaluate(arguments) -> None:
    model, metadata = load_benefit_model(arguments.model)
    config = BenefitConfig(**metadata["config"])
    rows, summary = evaluate_benefit(
        model, config, arguments.samples_per_profile, arguments.seed,
        arguments.bootstrap_samples, arguments.bootstrap_seed,
    )
    save_benefit_evaluation(rows, summary, arguments.output)
    print(f"Tuned RR score: {summary['mean_rr_score']:.6f}")
    print(f"Benefit score: {summary['mean_benefit_score']:.6f}")
    print(f"Relative improvement: {summary['relative_improvement_vs_rr']:.2%}")
    print(f"Paired 95% CI: [{summary['paired_difference_vs_rr']['ci_low']:.6f}, {summary['paired_difference_vs_rr']['ci_high']:.6f}]")
    print(f"Eligible: {summary['eligible']}")
    print(f"Recommendation: {summary['recommended_policy']}")
    print(f"Results: {arguments.output}")


def _benefit_latency(arguments) -> None:
    model, metadata = load_benefit_model(arguments.model)
    rows, summary = run_benefit_latency(
        model, BenefitConfig(**metadata["config"]),
        arguments.samples_per_profile, arguments.seed, arguments.warmups,
    )
    evaluation_path = Path(arguments.output) / "summary.json"
    if evaluation_path.exists():
        evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
        summary["score_improvement_gate"] = evaluation["score_improvement_gate"]
        summary["confidence_gate"] = evaluation["confidence_gate"]
        summary["eligible"] = all((
            summary["passes_latency_gate"], summary["score_improvement_gate"], summary["confidence_gate"]
        ))
        summary["recommended_policy"] = "Benefit selector" if summary["eligible"] else "Round Robin"
        evaluation.update({
            "full_latency_gate": summary["passes_latency_gate"],
            "eligible": summary["eligible"],
            "recommended_policy": summary["recommended_policy"],
        })
        evaluation_path.write_text(json.dumps(evaluation, indent=2), encoding="utf-8")
    save_benefit_latency(rows, summary, arguments.output)
    print(f"P99 gate: {summary['passes_latency_gate']}")
    for size, metrics in summary["latency"].items():
        print(f"{size}: p50={metrics['p50_ms']:.6f} ms p95={metrics['p95_ms']:.6f} ms p99={metrics['p99_ms']:.6f} ms")
    if "recommended_policy" in summary:
        print(f"Final recommendation: {summary['recommended_policy']}")
    print(f"Results: {arguments.output}")


def _mlfq_evaluate(arguments) -> None:
    rows, summary = evaluate_mlfq(
        arguments.samples_per_profile, arguments.seed,
        arguments.tuning_samples_per_profile, arguments.tuning_seed,
        arguments.bootstrap_samples, arguments.bootstrap_seed,
    )
    save_mlfq_evaluation(rows, summary, arguments.output)
    print(f"Tuned RR quantum: {summary['rr_quantum']}")
    for name, metrics in summary["policies"].items():
        print(f"{name}: score={metrics['mean_score']:.6f} response={metrics['mean_response_time']:.3f}")
    print(f"MLFQ score gate: {summary['score_gate']}")
    print(f"MLFQ fairness gate: {summary['fairness_gate']}")
    print("Final decision pending `python main.py mlfq-latency`.")
    print(f"Results: {arguments.output}")


def _mlfq_latency(arguments) -> None:
    output = Path(arguments.output)
    evaluation_path = output / "summary.json"
    if not evaluation_path.exists():
        raise SystemExit(f"MLFQ summary not found: {evaluation_path}. Run `python main.py mlfq-evaluate` first.")
    evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    rows, latency = run_mlfq_latency(
        evaluation["rr_quantum"], arguments.samples_per_profile, arguments.seed, arguments.warmups
    )
    final = finalize_mlfq_summary(evaluation, latency)
    evaluation_path.write_text(json.dumps(final, indent=2), encoding="utf-8")
    save_mlfq_latency(rows, latency, output)
    for name, gate in latency["policy_gate"].items():
        print(f"{name} latency gate: {gate['passes_gate']}")
    print(f"MLFQ wins: {final['mlfq_wins']}")
    print(f"Add ML next: {final['recommend_ml_next']}")
    print(f"Recommended policy: {final['recommended_policy']}")
    print(f"Results: {arguments.output}")


def _demo(arguments) -> None:
    from autoscheduler.demo import run_demo

    run_demo(no_color=arguments.no_color)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Adaptive CPU scheduling simulator")
    commands = parser.add_subparsers(dest="command", required=True)

    train = commands.add_parser("train", help="generate oracle labels and train a decision tree")
    train.add_argument("--samples-per-profile", type=int, default=500)
    train.add_argument("--seed", type=int, default=42)
    train.add_argument("--model", default=str(DEFAULT_MODEL))
    train.add_argument("--dataset", default="artifacts/training.csv")
    train.set_defaults(handler=_train)

    compare = commands.add_parser("compare", help="compare static and adaptive scheduling")
    compare.add_argument("--profile", choices=PROFILES, default="mixed")
    compare.add_argument("--seed", type=int, default=42)
    compare.add_argument("--process-count", type=int)
    compare.add_argument("--model", default=str(DEFAULT_MODEL))
    compare.set_defaults(handler=_compare)

    evaluate = commands.add_parser("evaluate", help="run held-out evaluation")
    evaluate.add_argument("--samples-per-profile", type=int, default=200)
    evaluate.add_argument("--seed", type=int, default=2026)
    evaluate.add_argument("--model", default=str(DEFAULT_MODEL))
    evaluate.add_argument("--output", default="results")
    evaluate.add_argument("--tune-priority-rr", action="store_true")
    evaluate.add_argument("--tune-samples-per-profile", type=int, default=500)
    evaluate.add_argument("--tune-seed", type=int, default=42)
    evaluate.set_defaults(handler=_evaluate)

    latency = commands.add_parser("latency", help="benchmark scheduler decision latency")
    latency.add_argument("--samples-per-profile", type=int, default=20)
    latency.add_argument("--warmups", type=int, default=5)
    latency.add_argument("--seed", type=int, default=3030)
    latency.add_argument("--model", default=str(DEFAULT_MODEL))
    latency.add_argument("--score-summary", default="results/summary.json")
    latency.add_argument("--output", default="results")
    latency.set_defaults(handler=_latency)

    model_bakeoff = commands.add_parser("model-bakeoff", help="run the real-trace action-cost prototype bake-off")
    model_bakeoff.add_argument("path", help="development-only action-cost CSV from real-dataset")
    model_bakeoff.add_argument("--config", default="configs/real_desktop_ml.json")
    model_bakeoff.add_argument("--output", default="results/real_desktop_ml/prototype_bakeoff")
    model_bakeoff.set_defaults(handler=_model_bakeoff)

    dynamic_train = commands.add_parser("dynamic-train", help="tune and train safe epoch router")
    dynamic_train.add_argument("--traces", type=int, default=144)
    dynamic_train.add_argument("--tuning-traces", type=int, default=60)
    dynamic_train.add_argument("--seed", type=int, default=42)
    dynamic_train.add_argument("--policy-track", choices=("realistic", "oracle_simulation"), default="realistic")
    dynamic_train.add_argument("--model-kind", choices=("classifier", "policy_cost"), default="policy_cost")
    dynamic_train.add_argument("--initial-policy", default="Round Robin")
    dynamic_train.add_argument("--fallback-policy", default="hold", help="eligible policy or hold (historical behavior)")
    dynamic_train.add_argument("--workload-suite", choices=("development", "historical"), default="development")
    dynamic_train.add_argument("--epoch-ticks", type=int, default=10)
    dynamic_train.add_argument("--dwell-epochs", type=int, default=2)
    dynamic_train.add_argument("--confidence", type=float, default=.8)
    dynamic_train.add_argument("--tune-router", action="store_true", help="optional legacy synthetic router search")
    dynamic_train.add_argument("--model", default=str(DEFAULT_DYNAMIC_MODEL))
    dynamic_train.add_argument("--dataset", default="artifacts/dynamic_v3/training.csv")
    dynamic_train.set_defaults(handler=_dynamic_train)

    dynamic_evaluate = commands.add_parser("dynamic-evaluate", help="evaluate safe epoch router")
    dynamic_evaluate.add_argument("--traces", type=int, default=1_000)
    dynamic_evaluate.add_argument("--seed", type=int, default=2026)
    dynamic_evaluate.add_argument("--model", default=str(DEFAULT_DYNAMIC_MODEL))
    dynamic_evaluate.add_argument("--output", default="results/dynamic_v3")
    dynamic_evaluate.set_defaults(handler=_dynamic_evaluate)

    dynamic_demo = commands.add_parser("dynamic-demo", help="train, select, and demonstrate Dynamic V3 end to end")
    dynamic_demo.add_argument("--train-traces", type=int, default=144)
    dynamic_demo.add_argument("--validation-traces", type=int, default=60)
    dynamic_demo.add_argument("--train-seed", type=int, default=7301)
    dynamic_demo.add_argument("--validation-seed", type=int, default=7302)
    dynamic_demo.add_argument("--demo-seed", type=int, default=9090)
    dynamic_demo.add_argument("--config", default="configs/real_desktop_ml.json")
    dynamic_demo.add_argument("--output", default="results/dynamic_v3_demo")
    dynamic_demo.add_argument("--artifacts", default="artifacts/dynamic_v3_demo")
    dynamic_demo.set_defaults(handler=_dynamic_demo)

    benefit_train = commands.add_parser("benefit-train", help="train conservative RR-versus-SRTF benefit regressor")
    benefit_train.add_argument("--samples-per-profile", type=int, default=500)
    benefit_train.add_argument("--seed", type=int, default=42)
    benefit_train.add_argument("--model", default=str(DEFAULT_BENEFIT_ROOT / "model.joblib"))
    benefit_train.add_argument("--dataset", default=str(DEFAULT_BENEFIT_ROOT / "training.csv"))
    benefit_train.set_defaults(handler=_benefit_train)

    benefit_evaluate = commands.add_parser("benefit-evaluate", help="evaluate RR-versus-SRTF benefit selector")
    benefit_evaluate.add_argument("--samples-per-profile", type=int, default=200)
    benefit_evaluate.add_argument("--seed", type=int, default=4040)
    benefit_evaluate.add_argument("--bootstrap-samples", type=int, default=10_000)
    benefit_evaluate.add_argument("--bootstrap-seed", type=int, default=4041)
    benefit_evaluate.add_argument("--model", default=str(DEFAULT_BENEFIT_ROOT / "model.joblib"))
    benefit_evaluate.add_argument("--output", default=str(DEFAULT_BENEFIT_ROOT))
    benefit_evaluate.set_defaults(handler=_benefit_evaluate)

    benefit_latency = commands.add_parser("benefit-latency", help="benchmark benefit decision latency")
    benefit_latency.add_argument("--samples-per-profile", type=int, default=20)
    benefit_latency.add_argument("--warmups", type=int, default=5)
    benefit_latency.add_argument("--seed", type=int, default=5050)
    benefit_latency.add_argument("--model", default=str(DEFAULT_BENEFIT_ROOT / "model.joblib"))
    benefit_latency.add_argument("--output", default=str(DEFAULT_BENEFIT_ROOT))
    benefit_latency.set_defaults(handler=_benefit_latency)

    mlfq_evaluate = commands.add_parser("mlfq-evaluate", help="evaluate fixed MLFQ against static baselines")
    mlfq_evaluate.add_argument("--samples-per-profile", type=int, default=200)
    mlfq_evaluate.add_argument("--seed", type=int, default=6060)
    mlfq_evaluate.add_argument("--tuning-samples-per-profile", type=int, default=500)
    mlfq_evaluate.add_argument("--tuning-seed", type=int, default=42)
    mlfq_evaluate.add_argument("--bootstrap-samples", type=int, default=10_000)
    mlfq_evaluate.add_argument("--bootstrap-seed", type=int, default=6061)
    mlfq_evaluate.add_argument("--output", default=str(DEFAULT_MLFQ_ROOT))
    mlfq_evaluate.set_defaults(handler=_mlfq_evaluate)

    mlfq_latency = commands.add_parser("mlfq-latency", help="benchmark MLFQ experiment decision latency")
    mlfq_latency.add_argument("--samples-per-profile", type=int, default=20)
    mlfq_latency.add_argument("--warmups", type=int, default=5)
    mlfq_latency.add_argument("--seed", type=int, default=6062)
    mlfq_latency.add_argument("--output", default=str(DEFAULT_MLFQ_ROOT))
    mlfq_latency.set_defaults(handler=_mlfq_latency)

    demo = commands.add_parser("demo", help="open interactive experiment demo")
    demo.add_argument("--no-color", action="store_true")
    demo.set_defaults(handler=_demo)

    real_config = commands.add_parser("real-config", help="validate the frozen real-trace experiment contract")
    real_config.add_argument("--config", default="configs/real_desktop_ml.json")
    real_config.set_defaults(handler=_real_config)

    real_import = commands.add_parser("real-trace-import", help="import a trace-cmd report")
    real_import.add_argument("--report", required=True)
    real_import.add_argument("--metadata", required=True)
    real_import.add_argument("--output", required=True)
    real_import.add_argument("--trace-id", required=True)
    real_import.set_defaults(handler=_real_trace_import)

    real_validate = commands.add_parser("real-trace-validate", help="validate canonical trace JSONL")
    real_validate.add_argument("path")
    real_validate.set_defaults(handler=_real_trace_validate)

    real_clean = commands.add_parser("real-trace-clean", help="anonymize completed canonical trace JSONL")
    real_clean.add_argument("paths", nargs="+")
    real_clean.add_argument("--capture-session", required=True)
    real_clean.add_argument("--output", required=True)
    real_clean.set_defaults(handler=_real_trace_clean)

    real_features = commands.add_parser("real-features", help="extract observed-only feature rows")
    real_features.add_argument("paths", nargs="+")
    real_features.add_argument("--output", required=True)
    real_features.add_argument("--config", default="configs/real_desktop_ml.json")
    real_features.set_defaults(handler=_real_features)

    real_split = commands.add_parser("real-split", help="create a leakage-safe real-trace split manifest")
    real_split.add_argument("path")
    real_split.add_argument("--output", required=True)
    real_split.add_argument("--config", default="configs/real_desktop_ml.json")
    real_split.set_defaults(handler=_real_split)

    real_dataset = commands.add_parser("real-dataset", help="build replay-only development action-cost rows")
    real_dataset.add_argument("paths", nargs="+")
    real_dataset.add_argument("--output", required=True)
    real_dataset.add_argument("--config", default="configs/real_desktop_ml.json")
    real_dataset.set_defaults(handler=_real_dataset)

    synthetic = commands.add_parser("real-synthetic-capture", help="create development-only synthetic canonical traces")
    synthetic.add_argument("--repetitions", type=int, default=60)
    synthetic.add_argument("--seed", type=int, default=9001)
    synthetic.add_argument("--output", required=True)
    synthetic.set_defaults(handler=_real_synthetic_capture)

    replay = commands.add_parser("real-replay-build", help="build offline replay workloads from canonical traces")
    replay.add_argument("paths", nargs="+")
    replay.add_argument("--output", required=True)
    replay.set_defaults(handler=_real_replay_build)
    return parser


def main(argv=None) -> None:
    arguments = build_parser().parse_args(argv)
    arguments.handler(arguments)
