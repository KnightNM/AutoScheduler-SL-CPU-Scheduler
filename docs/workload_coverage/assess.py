"""Read-only coverage diagnostics; never trains or writes to production/results.

Run from any directory. Outputs live beside this script in output/.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import math
import random
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from autoscheduler.dynamic import generate_dynamic_workload
from autoscheduler.evaluation import ALGORITHMS, SCORE_WEIGHTS, compare_algorithms, oracle_label
from autoscheduler.features import FEATURE_NAMES, extract_features
from autoscheduler.workloads import PROFILES, generate_workload
from simulator.process import Process


def read_csv(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def fingerprint():
    files = [ROOT / "main.py", ROOT / "requirements.txt"]
    for folder in ("scheduler", "simulator", "autoscheduler", "tests", "results", "artifacts"):
        files.extend(p for p in (ROOT / folder).rglob("*")
                     if p.is_file() and "__pycache__" not in p.parts)
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(files)}


def stats(values):
    x = np.asarray(values, dtype=float)
    return dict(mean=float(x.mean()), variance=float(x.var()), median=float(np.median(x)),
                p95=float(np.quantile(x, .95)), minimum=float(x.min()), maximum=float(x.max()))


def measure(processes):
    f = extract_features(processes)
    arrivals = sorted(p.arrival_time for p in processes)
    gaps = np.diff(arrivals)
    cpu = [p.burst_time for p in processes]
    bursts = [b for p in processes for b in p.cpu_bursts]
    ticks = np.bincount(np.asarray(arrivals) - min(arrivals))
    # Arrival-window load is finite-cohort demand / one CPU's capacity in W ticks.
    window = max(arrivals) - min(arrivals) + 1
    return dict(**f, arrival_interval_mean=float(gaps.mean()),
                arrival_interval_variance=float(gaps.var()),
                individual_burst_mean=float(np.mean(bursts)),
                individual_burst_variance=float(np.var(bursts)),
                long_job_ratio=float(np.mean(np.asarray(cpu) > 40)),
                total_cpu_demand=sum(cpu), arrival_window=window,
                offered_load=sum(cpu) / window,
                arrival_zero_gap_ratio=float(np.mean(gaps == 0)),
                arrival_fano=float(ticks.var() / ticks.mean()),
                arrival_peak_batch=int(ticks.max()),
                cpu_top_share=max(cpu) / sum(cpu),
                cpu_hhi=sum((v / sum(cpu)) ** 2 for v in cpu))


def feature_analysis(rows):
    x = np.array([[float(r[n]) for n in FEATURE_NAMES] for r in rows])
    pooled = np.corrcoef(x, rowvar=False)
    within = x.copy()
    eta = {}
    for j, name in enumerate(FEATURE_NAMES):
        total = float(((x[:, j] - x[:, j].mean()) ** 2).sum())
        residual = 0.
        for profile in PROFILES:
            mask = np.array([r["profile"] == profile for r in rows])
            within[mask, j] -= x[mask, j].mean()
            residual += float((within[mask, j] ** 2).sum())
        eta[name] = 1 - residual / total if total else None
    with np.errstate(invalid="ignore", divide="ignore"):
        centered = np.corrcoef(within, rowvar=False)
    pairs = sorted((dict(a=a, b=b, r=float(pooled[i, j]))
                    for i, a in enumerate(FEATURE_NAMES)
                    for j, b in enumerate(FEATURE_NAMES) if i < j),
                   key=lambda r: abs(r["r"]), reverse=True)
    # Descriptive overlap: standardize on the pooled data, then leave-one-out 1-NN.
    # This does not fit/retrain the scheduling classifier or establish causation.
    z = (x - x.mean(axis=0)) / x.std(axis=0)
    labels = np.array([PROFILES.index(r["profile"]) for r in rows])
    confusion = np.zeros((5, 5), dtype=int)
    for start in range(0, len(x), 200):
        d = ((z[start:start + 200, None, :] - z[None, :, :]) ** 2).sum(axis=2)
        d[np.arange(len(d)), np.arange(start, start + len(d))] = np.inf
        predicted = labels[d.argmin(axis=1)]
        np.add.at(confusion, (labels[start:start + len(d)], predicted), 1)
    summaries = {}
    for profile in PROFILES:
        group = [r for r in rows if r["profile"] == profile]
        summaries[profile] = {n: dict(**stats([float(r[n]) for r in group]),
                                     unique=len({float(r[n]) for r in group}))
                              for n in FEATURE_NAMES}
    return dict(correlation=pooled.tolist(), within_profile_correlation=
                [[float(v) if np.isfinite(v) else None for v in row] for row in centered],
                strongest_pairs=pairs, profile_eta_squared=eta, profile_features=summaries,
                profile_neighbor_accuracy=float(np.trace(confusion) / len(x)),
                profile_neighbor_confusion=confusion.tolist())


def changed(p, *, arrival=None, cpu=None, io=None, priority=None):
    cpu = tuple(cpu if cpu is not None else p.cpu_bursts)
    return Process(p.pid, p.arrival_time if arrival is None else arrival, sum(cpu),
                   p.priority if priority is None else priority, cpu,
                   tuple(p.io_bursts if io is None else io))


def stress_workload(family, seed):
    r = random.Random(seed)
    if family.startswith("count_"):
        return generate_workload("mixed", seed, int(family.split("_")[1])).processes
    if family == "phase_shift":
        return generate_dynamic_workload(seed, phase_profiles=("batch", "io_intensive", "cpu_intensive")).processes
    base = generate_workload("mixed", seed).processes
    if family == "poisson_arrivals":
        # Continuous exponential gaps, rounded cumulative event times to integer ticks.
        clock = 0.
        result = []
        for i, p in enumerate(base):
            clock += r.expovariate(1 / 5) if i else 0
            result.append(changed(p, arrival=round(clock)))
        return result
    if family == "sparse_arrivals":
        return [changed(p, arrival=i * 200) for i, p in enumerate(base)]
    if family == "bursty_arrivals":
        return [changed(p, arrival=(i // 4) * 60) for i, p in enumerate(base)]
    if family == "heavy_tail":
        # Deliberately winsorized diagnostic Pareto bursts; not a real trace claim.
        return [changed(p, cpu=[min(500, max(1, round(3 * r.paretovariate(1.2))))
                                for _ in p.cpu_bursts]) for p in base]
    if family == "extreme_io":
        return [changed(p, cpu=(1,) * 8, io=(100,) * 7) for p in base]
    if family == "urgent_minority":
        return [changed(p, priority=1 if i == len(base) - 1 else 20)
                for i, p in enumerate(base)]
    raise ValueError(family)


def score_column(policy):
    return "score_" + policy.lower().replace(" ", "_")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples-per-profile", type=int, default=500)
    parser.add_argument("--seed", type=int, default=73013)
    parser.add_argument("--stress-samples", type=int, default=12)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "output")
    args = parser.parse_args()
    if args.samples_per_profile < 2 or args.stress_samples < 1:
        parser.error("need at least 2 profile samples and 1 stress sample")
    output = args.output.resolve()
    if output == ROOT or not output.is_relative_to(ROOT / "docs/workload_coverage"):
        parser.error("output must be inside docs/workload_coverage/")
    output.mkdir(parents=True, exist_ok=True)
    before = fingerprint()
    saved = ROOT / "results/six_policy"
    training = read_csv(saved / "training.csv")
    evaluation = read_csv(saved / "evaluation.csv")
    bundle = joblib.load(saved / "model.joblib")
    model = bundle["model"]
    config = bundle["metadata"]["priority_rr_config"]
    assert tuple(bundle["features"]) == FEATURE_NAMES
    assert bundle["metadata"]["policy_set"] == list(ALGORITHMS)
    fresh, profile_stats, raw_metrics = [], {}, []
    for index, profile in enumerate(PROFILES):
        cpu, bursts, gaps, priorities = [], [], [], []
        for sample in range(args.samples_per_profile):
            seed = args.seed * 10_000_000 + index * 1_000_000 + sample
            ps = generate_workload(profile, seed).processes
            row = dict(profile=profile, seed=seed, **measure(ps))
            fresh.append(row)
            cpu.extend(p.burst_time for p in ps)
            bursts.extend(b for p in ps for b in p.cpu_bursts)
            gaps.extend(np.diff(sorted(p.arrival_time for p in ps)))
            priorities.extend(p.priority for p in ps)
        group = [x for x in fresh if x["profile"] == profile]
        profile_stats[profile] = dict(workloads=len(group), processes=len(cpu),
            total_cpu_per_process=stats(cpu), individual_cpu_bursts=stats(bursts),
            arrival_intervals=stats(gaps), priorities=stats(priorities),
            workload_metrics={k: stats([v[k] for v in group])
                              for k in group[0] if k not in ("profile", "seed")})
    feature = feature_analysis(fresh)
    saved_feature = feature_analysis(training)
    write_csv(output / "workloads.csv", fresh)
    write_csv(output / "feature_correlations.csv", [dict(feature=n, **dict(zip(FEATURE_NAMES, row)))
              for n, row in zip(FEATURE_NAMES, feature["correlation"])])
    # Reconstruct every saved workload to check feature/schema/seed consistency.
    regenerated = []
    mismatch = 0
    for row in training:
        actual = extract_features(generate_workload(row["profile"], int(row["seed"])).processes)
        mismatch += any(not math.isclose(actual[n], float(row[n]), abs_tol=1e-10) for n in FEATURE_NAMES)
    for row in evaluation:
        features = extract_features(generate_workload(row["profile"], int(row["seed"])).processes)
        regenerated.append([features[n] for n in FEATURE_NAMES])
    pred = model.predict(regenerated)
    selected_mismatch = sum(a != b["selected"] for a, b in zip(pred, evaluation))
    tree_rules = []
    tree = model.tree_
    for node in range(tree.node_count):
        if tree.feature[node] >= 0:
            tree_rules.append(dict(node=node, feature=FEATURE_NAMES[tree.feature[node]], threshold=float(tree.threshold[node])))
    labels = {profile: dict(Counter(r["label"] for r in training if r["profile"] == profile)) for profile in PROFILES}
    per_profile = {}
    for profile in PROFILES:
        group = [r for r in evaluation if r["profile"] == profile]
        per_profile[profile] = dict(oracle=dict(Counter(r["oracle"] for r in group)),
            selected=dict(Counter(r["selected"] for r in group)),
            accuracy=float(np.mean([int(r["correct"]) for r in group])),
            regret=float(np.mean([float(r["regret"]) for r in group])),
            rr_accuracy=float(np.mean([r["oracle"] == "Round Robin" for r in group])),
            adaptive_minus_rr=float(np.mean([float(r[score_column(r["selected"])]) - float(r["score_round_robin"]) for r in group])))
    low = np.array([min(float(r[n]) for r in training) for n in FEATURE_NAMES])
    high = np.array([max(float(r[n]) for r in training) for n in FEATURE_NAMES])
    # Evaluation-only stress; settings/model/weights unchanged. No inferential gates.
    stress = []
    families = ("count_100", "count_1000", "poisson_arrivals", "sparse_arrivals", "bursty_arrivals",
                "heavy_tail", "extreme_io", "urgent_minority", "phase_shift")
    for family_index, family in enumerate(families):
        count = min(3, args.stress_samples) if family == "count_1000" else args.stress_samples
        for sample in range(count):
            seed = args.seed * 100_000 + family_index * 1_000 + sample
            ps = stress_workload(family, seed)
            f = extract_features(ps)
            row_x = np.array([f[n] for n in FEATURE_NAMES])
            selected = str(model.predict([row_x])[0])
            results = compare_algorithms(ps, config)
            oracle, scores = oracle_label(results)
            stress.append(dict(family=family, seed=seed, selected=selected, oracle=oracle,
                correct=int(selected == oracle), regret=scores[selected] - scores[oracle],
                tied_best=";".join(n for n, score in scores.items() if math.isclose(score, scores[oracle], abs_tol=1e-12, rel_tol=0)),
                adaptive_minus_rr=scores[selected] - scores["Round Robin"],
                out_of_range_features=";".join(n for j, n in enumerate(FEATURE_NAMES) if row_x[j] < low[j] or row_x[j] > high[j]),
                **measure(ps), **{score_column(n): s for n, s in scores.items()},
                rr_utilization=results["Round Robin"].cpu_utilization,
                rr_idle_time=results["Round Robin"].idle_time))
        print("stress complete:", family, flush=True)
    write_csv(output / "stress.csv", stress)
    stress_summary = {}
    for family in families:
        group = [r for r in stress if r["family"] == family]
        stress_summary[family] = dict(samples=len(group), oracle=dict(Counter(r["oracle"] for r in group)),
            selected=dict(Counter(r["selected"] for r in group)),
            accuracy=float(np.mean([r["correct"] for r in group])),
            mean_regret=float(np.mean([r["regret"] for r in group])),
            mean_adaptive_minus_rr=float(np.mean([r["adaptive_minus_rr"] for r in group])),
            envelope_outside=sum(bool(r["out_of_range_features"]) for r in group),
            tied_best_workloads=sum(";" in r["tied_best"] for r in group),
            mean_rr_utilization=float(np.mean([r["rr_utilization"] for r in group])))
    # Inspect metric contributions with the original six-policy normalization/weights.
    for i, profile in enumerate(PROFILES):
        for sample in range(30):
            seed = args.seed * 10_000_000 + i * 1_000_000 + sample
            results = compare_algorithms(generate_workload(profile, seed).processes, config)
            for metric, weight in SCORE_WEIGHTS.items():
                vals = {n: getattr(v, metric) for n, v in results.items()}
                lo, hi = min(vals.values()), max(vals.values())
                for n, v in vals.items():
                    normalized = 0. if lo == hi else ((hi-v) if metric in ("throughput", "cpu_utilization") else (v-lo)) / (hi-lo)
                    raw_metrics.append(dict(profile=profile, seed=seed, policy=n, metric=metric,
                                            raw=v, contribution=weight * normalized))
    write_csv(output / "metric_contributions.csv", raw_metrics)
    contributions = {n: {metric: float(np.mean([r["contribution"] for r in raw_metrics if r["policy"] == n and r["metric"] == metric])) for metric in SCORE_WEIGHTS} for n in ALGORITHMS}
    # Readable charts: all axes use simulated ticks or dimensionless generator features.
    fig, axes = plt.subplots(3, 3, figsize=(15, 11))
    for ax, name in zip(axes.flat, FEATURE_NAMES):
        ax.boxplot([[r[name] for r in fresh if r["profile"] == p] for p in PROFILES], tick_labels=["Int", "Batch", "CPU", "IO", "Mix"], showfliers=False)
        ax.set_title(name)
    fig.suptitle(f"Synthetic generator: {args.samples_per_profile} workloads/profile")
    fig.tight_layout(); fig.savefig(output / "feature_distributions.png", dpi=160); plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(16, 7), layout="constrained")
    for ax, matrix, title in zip(axes, [feature["correlation"], feature["within_profile_correlation"]], ["Pooled Pearson correlations", "Profile-centered Pearson correlations"]):
        im = ax.imshow(np.array(matrix, dtype=float), vmin=-1, vmax=1, cmap="coolwarm")
        ax.set_xticks(range(9), FEATURE_NAMES, rotation=75, ha="right")
        ax.set_yticks(range(9), FEATURE_NAMES); ax.set_title(title)
    fig.colorbar(im, ax=axes, shrink=.7, fraction=.025, pad=.03)
    fig.savefig(output / "correlations.png", dpi=160); plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    for p in PROFILES:
        group = [r for r in fresh if r["profile"] == p]
        axes[0].scatter([r["short_job_ratio"] for r in group], [r["burst_variance"] for r in group], s=8, alpha=.3, label=p)
        axes[1].scatter([r["io_frequency"] for r in group], [r["io_cpu_ratio"] for r in group], s=8, alpha=.3)
    axes[0].set(xlabel="short-job ratio", ylabel="variance of process total CPU (ticks²)")
    axes[1].set(xlabel="I/O events/process", ylabel="I/O-to-CPU time ratio")
    axes[0].legend(fontsize=8); fig.tight_layout(); fig.savefig(output / "profile_overlap.png", dpi=160); plt.close(fig)
    after = fingerprint()
    assert before == after, "Protected inputs changed during diagnostics"
    identities = []
    for metric_a, metric_b, weight_a, weight_b in (
        ("avg_waiting_time", "avg_turnaround_time", .30, .20),
        ("cpu_utilization", "throughput", .15, .10),
    ):
        left = [r["contribution"] / weight_a for r in raw_metrics if r["metric"] == metric_a]
        right = [r["contribution"] / weight_b for r in raw_metrics if r["metric"] == metric_b]
        identities.append(dict(a=metric_a, b=metric_b, max_normalized_difference=float(np.max(np.abs(np.array(left)-right)))))
    result = dict(profile_statistics=profile_stats, features=feature, saved_training_features=saved_feature,
        training_labels=labels, evaluation_profiles=per_profile, stress=stress_summary,
        metric_contributions=contributions, tree_splits=tree_rules,
        score_metric_identities=identities,
        validation=dict(saved_training_feature_mismatches=mismatch, saved_evaluation_prediction_mismatches=selected_mismatch,
                        train_evaluation_seed_overlap=len({r["seed"] for r in training} & {r["seed"] for r in evaluation}),
                        fresh_saved_seed_overlap=len({str(r["seed"]) for r in fresh} & {r["seed"] for r in training + evaluation}),
                        protected_files_unchanged=before == after),
        manifest=dict(seed=args.seed, samples_per_profile=args.samples_per_profile,
                      stress_samples=args.stress_samples, git_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                      python=sys.version, packages={n: importlib.metadata.version(n) for n in ("numpy", "scipy", "matplotlib", "scikit-learn", "joblib")},
                      protected_sha256=before,
                      script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()))
    (output / "assessment.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print("Wrote", output)
    print("Validation:", result["validation"])


if __name__ == "__main__":
    main()
