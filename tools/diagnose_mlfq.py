"""Read-only scheduling diagnostics: no model fitting or production changes."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import copy
import csv
import hashlib
import json
from pathlib import Path
import random
from statistics import mean, pvariance
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autoscheduler.dynamic import (
    DYNAMIC_FEATURE_NAMES, DYNAMIC_POLICY_NAMES, DynamicRouterConfig,
    _dispatch, _new_state, _policy_config, _prediction, _rebuild_ready, _release,
    _run_to_completion, _simulation, _switch_policy, _percentile,
    extract_dynamic_features, generate_dynamic_workload, run_dynamic,
)
from autoscheduler.evaluation import (
    ALGORITHMS, compare_algorithms, score_result_against_reference, score_results,
)
from autoscheduler.experiments import paired_bootstrap_ci
from autoscheduler.fairness import aggregate_fairness
from autoscheduler.model import load_model
from simulator.process import Process


CONFIG = DynamicRouterConfig(10, 2, .8)


def _available(state):
    _release(state, state.current_time)
    if not state.ready:
        times = [p.arrival_time for p in state.pending] + [t for t, *_ in state.blocked]
        if times:
            state.current_time = min(times)
            _release(state, state.current_time)


def run_controlled(processes, config=CONFIG, *, model=None, initial="MLFQ", target=None,
                   capture=False, sticky_mlfq=False):
    """Analysis-only routing control, checked against the frozen router in tests."""
    state = _new_state(processes)
    rr = _policy_config(None)
    active, last_switch, next_epoch = initial, 0, config.epoch_ticks
    events = []
    while state.pending or state.ready or state.blocked:
        _available(state)
        if state.current_time >= next_epoch and state.ready:
            while next_epoch <= state.current_time:
                next_epoch += config.epoch_ticks
            dwell = max(0, last_switch + config.dwell_epochs * config.epoch_ticks - state.current_time)
            features = extract_dynamic_features(state, active, dwell)
            costs = None
            if model is not None and not (sticky_mlfq and active == "MLFQ"):
                selected, confidence = _prediction(model, features)
                margin_ok = model.switch_allowed(features, active, selected)
                costs = list(map(float, model.regressor.predict([[features[n] for n in DYNAMIC_FEATURE_NAMES]])[0]))
            else:
                selected, confidence, margin_ok = target or active, 1., True
            accepted = selected != active and confidence >= config.confidence_threshold and not dwell and margin_ok
            event = {"time": state.current_time, "previous": active, "selected": selected,
                     "accepted": bool(accepted), "dwell": dwell, "features": features,
                     "predicted_costs": costs}
            if capture and (accepted or model is None):
                event["state"] = copy.deepcopy(state)
            if accepted:
                _switch_policy(state, active, selected)
                active, last_switch = selected, state.current_time
                _rebuild_ready(state, active, rr)
            event["active"] = active
            events.append(event)
            state.recent_arrivals = state.io_returns = 0
        _dispatch(state, active, rr)
    return _simulation(state, "Diagnostic control"), events


def trial_action(state, active, action, horizon, tail):
    """Known-future counterfactual for diagnosis only; never an inference feature."""
    trial = copy.deepcopy(state)
    rr = _policy_config(None)
    start = trial.current_time
    _switch_policy(trial, active, action)
    if horizon is None:
        _run_to_completion(trial, action, rr)
        return _simulation(trial, action), trial.current_time - start
    while (trial.pending or trial.ready or trial.blocked) and trial.current_time < start + horizon:
        _dispatch(trial, action, rr)
    duration = trial.current_time - start
    _switch_policy(trial, action, tail)
    _run_to_completion(trial, tail, rr)
    return _simulation(trial, action), duration


def workload_shape(processes):
    processes = list(processes)
    bursts = [burst for p in processes for burst in p.cpu_bursts]
    total_cpu = sum(bursts)
    total_io = sum(sum(p.io_bursts) for p in processes)
    span = max(p.arrival_time for p in processes) - min(p.arrival_time for p in processes)
    return {
        "process_count": len(processes), "arrival_span": span,
        "arrival_rate": len(processes) / max(1, span),
        "offered_cpu_per_arrival_tick": total_cpu / max(1, span),
        "cpu_burst_count": len(bursts), "cpu_burst_mean": mean(bursts),
        "cpu_burst_cv": pvariance(bursts) ** .5 / mean(bursts),
        "cpu_burst_max": max(bursts), "short_burst_fraction": mean(b <= 2 for b in bursts),
        "total_cpu": total_cpu, "total_io": total_io,
        "io_cpu_ratio": total_io / total_cpu,
        "io_process_fraction": mean(bool(p.io_bursts) for p in processes),
    }


def measured(result, references):
    return {
        "score": score_result_against_reference(result, references),
        "p95": _percentile([m.response_time for m in result.process_metrics], .95),
        "starvation": aggregate_fairness(result.process_metrics)["starvation_count"],
        "wait": result.avg_waiting_time, "response": result.avg_response_time,
        "turnaround": result.avg_turnaround_time,
        "context_switches": result.context_switches, "switch_time": result.context_switch_time,
    }


def one_departure_search(processes, references, baseline, checkpoints=8):
    _, events = run_controlled(processes, initial="MLFQ", target="MLFQ", capture=True)
    events = [e for e in events if not e["dwell"]]
    samples = min(checkpoints, len(events))
    positions = sorted({round(i * (len(events)-1) / max(1, samples-1)) for i in range(samples)})
    best = {kind: {"score": baseline["score"], "action": "MLFQ", "time": None,
                   "mode": "no_switch", "p95": baseline["p95"], "starvation": baseline["starvation"]}
            for kind in ("one_switch", "one_switch_safe", "excursion", "excursion_safe")}
    for index in positions:
        event = events[index]
        for action in DYNAMIC_POLICY_NAMES:
            if action == "MLFQ":
                continue
            for mode, horizon in (("one_switch", None), ("excursion", 20)):
                result, _ = trial_action(event["state"], "MLFQ", action, horizon, "MLFQ")
                values = measured(result, references)
                candidate = {**values, "action": action, "time": event["time"], "mode": mode}
                if values["score"] < best[mode]["score"] - 1e-12:
                    best[mode] = candidate
                if (values["p95"] <= baseline["p95"] + 1e-12
                        and values["starvation"] <= baseline["starvation"]
                        and values["score"] < best[mode+"_safe"]["score"] - 1e-12):
                    best[mode+"_safe"] = candidate
    return {"checkpoints": len(positions), "best": best}


def switch_counterfactual(event, references):
    state, active, selected = event["state"], event["previous"], event["selected"]
    original = {a: trial_action(state, active, a, 10, "Round Robin") for a in DYNAMIC_POLICY_NAMES}
    local_scores = score_results({a: r[0] for a, r in original.items()})
    fixed_scores = {a: score_result_against_reference(r[0], references) for a, r in original.items()}
    coherent = {a: measured(trial_action(state, active, a, 20, "MLFQ")[0], references)
                for a in (active, selected)}
    predicted = dict(zip(DYNAMIC_POLICY_NAMES, event["predicted_costs"]))
    short_action = selected != "Round Robin" and original[selected][1] < 20
    finished_at_boundary = original[selected][0].makespan <= state.current_time + original[selected][1]
    return {
        "time": event["time"], "previous": active, "selected": selected,
        "predicted_advantage": predicted[active] - predicted[selected],
        "original_label_advantage": local_scores[active] - local_scores[selected],
        "original_fixed_scale_advantage": fixed_scores[active] - fixed_scores[selected],
        "safe20_mlfq_tail_advantage": coherent[active]["score"] - coherent[selected]["score"],
        "selected_is_original_optimal": local_scores[selected] <= min(local_scores.values()) + 1e-12,
        "label_switches_back_before_dwell": short_action and not finished_at_boundary,
        "label_completed_before_dwell": short_action and finished_at_boundary,
        "local_vs_fixed_ranking_disagrees": min(local_scores, key=local_scores.get) != min(fixed_scores, key=fixed_scores.get),
    }


def stress_cases():
    """Separate development probes, never additions to the frozen evaluation."""
    for count in (3, 8, 24):
        for shape in ("uniform_short", "uniform_long", "bimodal", "heavy_tail"):
            for spacing in (0, 2, 20, 100):
                for io in (0, 10, 100):
                    randomizer = random.Random(9001 + count * 100 + io + spacing)
                    processes = []
                    for i in range(count):
                        burst = {"uniform_short": 2, "uniform_long": 20,
                                 "bimodal": 1 if i % 3 else 40,
                                 "heavy_tail": min(100, max(1, int(randomizer.paretovariate(1.5) * 3)))}[shape]
                        bursts = (burst,) * (3 if io else 1)
                        processes.append(Process(f"P{i:03}", i * spacing, sum(bursts),
                                                 priority=randomizer.randint(1,5), cpu_bursts=bursts,
                                                 io_bursts=(io, io) if io else ()))
                    yield f"n{count}_{shape}_spacing{spacing}_io{io}", processes


def _hashes(paths):
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(paths)) if p.is_file()}


def _write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("results/mlfq_dominance_20261019"))
    args = parser.parse_args()
    output = args.output
    if (output / "diagnostics.json").exists():
        raise ValueError("use a fresh diagnostics output path")
    output.mkdir(parents=True, exist_ok=True)
    protected = [*Path("results/dynamic_v2_20261019").rglob("*"),
                 *Path("artifacts/dynamic_v2_20261019").rglob("*"),
                 *Path("scheduler").glob("*.py"), *Path("simulator").glob("*.py"),
                 *Path("autoscheduler").glob("*.py"), *Path("configs").glob("*.json"), Path(__file__)]
    before = _hashes(protected)
    model = load_model("artifacts/dynamic_v2_20261019/candidates/policy_cost/model.joblib", DYNAMIC_FEATURE_NAMES)
    training_root = Path("artifacts/dynamic_v2_20261019/candidates")
    groups = json.loads((training_root/"split.json").read_text())["groups"]
    fitted_seeds = set(groups["train"] + groups["validation"])
    with (training_root/"training.csv").open(newline="") as file:
        training = [r for r in csv.DictReader(file) if int(r["seed"]) in fitted_seeds]
    feature_ranges = {name:(min(float(r[name]) for r in training), max(float(r[name]) for r in training))
                      for name in DYNAMIC_FEATURE_NAMES}
    runtime_active, outside_ranges = Counter(), Counter()
    reviews = after_arrivals = 0
    rows, decisions, counterfactuals, departures = [], [], [], []
    for index in range(1000):
        workload = generate_dynamic_workload(2026 * 1_000_000 + index)
        static = compare_algorithms(workload.processes, algorithms=(*ALGORITHMS, "MLFQ"))
        references = {name: static[name] for name in ALGORITHMS}
        values = {name: measured(result, references) for name, result in static.items()}
        baseline = values["MLFQ"]
        adaptive, events = run_controlled(workload.processes, model=model, initial="Round Robin", capture=index % 10 == 0)
        # An independently instrumented router must exactly reproduce frozen output.
        expected = run_dynamic(workload.processes, model, CONFIG)
        assert adaptive.timeline == expected.simulation.timeline
        assert adaptive.process_metrics == expected.simulation.process_metrics
        assert [(e["time"],e["selected"],e["active"],e["accepted"]) for e in events] == [
            (d.time,d.selected,d.active,d.accepted) for d in expected.decisions]
        rr_mlfq, _ = run_controlled(workload.processes, initial="Round Robin", target="MLFQ")
        mlfq_start, _ = run_controlled(workload.processes, initial="MLFQ", model=model)
        sticky, _ = run_controlled(workload.processes, initial="Round Robin", model=model, sticky_mlfq=True)
        row = {"seed": workload.seed, "profiles": "/".join(workload.phase_profiles),
               "first_profile": workload.phase_profiles[0],
               "profile_combination": "/".join(sorted(workload.phase_profiles)),
               **workload_shape(workload.processes)}
        for name, metrics in {**values, "adaptive": measured(adaptive,references),
                              "rr_then_mlfq": measured(rr_mlfq,references),
                              "mlfq_start_model": measured(mlfq_start,references),
                              "sticky_mlfq": measured(sticky,references)}.items():
            row.update({f"{name}:{metric}": value for metric,value in metrics.items()})
        row["winner"] = min(DYNAMIC_POLICY_NAMES, key=lambda p: values[p]["score"])
        row["accepted_switches"] = sum(e["accepted"] for e in events)
        rows.append(row)
        for event in events:
            event["seed"] = workload.seed
            event["after_last_arrival"] = event["time"] > max(p.arrival_time for p in workload.processes)
            reviews += 1
            after_arrivals += event["after_last_arrival"]
            runtime_active[event["previous"]] += 1
            for feature,(low,high) in feature_ranges.items():
                outside_ranges[feature] += int(not low <= event["features"][feature] <= high)
            if event["accepted"]:
                decisions.append({k:v for k,v in event.items() if k not in ("state", "features")})
        if index % 10 == 0:
            accepted = [e for e in events if e["accepted"]]
            for position in sorted({0,len(accepted)-1}) if accepted else []:
                counterfactuals.append({"seed":workload.seed, **switch_counterfactual(accepted[position], references)})
            departures.append({"seed":workload.seed, "baseline":baseline,
                               **one_departure_search(workload.processes,references,baseline)})
        if (index+1) % 100 == 0:
            print(f"Audited {index+1}/1000 frozen workloads", flush=True)
    _write_csv(output / "workload_breakdown.csv", rows)
    _write_csv(output / "switch_counterfactuals.csv", counterfactuals)
    strata, cuts = [], {}
    numeric_axes = ("arrival_rate","cpu_burst_mean","cpu_burst_cv","io_cpu_ratio")
    for axis in (*numeric_axes, "first_profile", "profile_combination", "process_count"):
        if axis in numeric_axes:
            cuts[axis] = [_percentile([r[axis] for r in rows], f) for f in (1/3,2/3)]
            def bucket(r):
                return ("low","middle","high")[sum(r[axis] > c for c in cuts[axis])]
        else:
            def bucket(r):
                return str(r[axis])
        for group in sorted({bucket(r) for r in rows}):
            subset = [r for r in rows if bucket(r) == group]
            strata.append({"axis":axis,"group":group,"traces":len(subset),
                           "mlfq_wins":sum(r["winner"]=="MLFQ" for r in subset),
                           "mlfq_score":mean(r["MLFQ:score"] for r in subset),
                           "rr_minus_mlfq":mean(r["Round Robin:score"]-r["MLFQ:score"] for r in subset),
                           "model_minus_mlfq":mean(r["adaptive:score"]-r["MLFQ:score"] for r in subset),
                           "mlfq_p95":mean(r["MLFQ:p95"] for r in subset),
                           "model_p95":mean(r["adaptive:p95"] for r in subset)})
    _write_csv(output / "strata.csv", strata)
    probes, witnesses = [], {}
    for name, processes in stress_cases():
        results = compare_algorithms(processes, algorithms=(*ALGORITHMS,"MLFQ"))
        refs = {p:results[p] for p in ALGORITHMS}
        scores = {p:score_result_against_reference(results[p],refs) for p in DYNAMIC_POLICY_NAMES}
        winner = min(scores,key=scores.get)
        strict = scores[winner] < scores["MLFQ"] - 1e-12
        probes.append({"case":name,"winner":winner,"strictly_beats_mlfq":strict,
                       "winner_minus_mlfq":scores[winner]-scores["MLFQ"],**workload_shape(processes)})
        if strict and winner not in witnesses:
            witnesses[winner] = {"case":name, "scores":scores,
                                 "processes":[{"pid":p.pid,"arrival":p.arrival_time,"cpu":p.cpu_bursts,
                                               "io":p.io_bursts,"priority":p.priority} for p in processes]}
    _write_csv(output / "development_probes.csv", probes)
    route_controls = {}
    for route in ("adaptive","rr_then_mlfq","mlfq_start_model","sticky_mlfq"):
        route_controls[route] = {"mean_score":mean(r[f"{route}:score"] for r in rows),
            "mean_p95":mean(r[f"{route}:p95"] for r in rows),
            "score_minus_mlfq":paired_bootstrap_ci([r[f"{route}:score"]-r["MLFQ:score"] for r in rows])}
    departure_summary = {}
    for mode in ("one_switch","one_switch_safe","excursion","excursion_safe"):
        differences = [d["best"][mode]["score"]-d["baseline"]["score"] for d in departures]
        departure_summary[mode] = {"workloads":len(departures),"wins":sum(x < -1e-12 for x in differences),
                                    "score_minus_mlfq":paired_bootstrap_ci(differences),
                                    "actions":dict(Counter(d["best"][mode]["action"] for d in departures))}
    audit = {
        "status":"POST_HOC_SYNTHETIC_DIAGNOSTICS_NOT_MODEL_SELECTION", "no_models_fitted":True,
        "evaluation":{"traces":1000,"seed":2026},
        "counterfactual_subset":"indices 0,10,...,990; first and last accepted switch; 8 MLFQ review checkpoints",
        "config":CONFIG.__dict__, "source_and_artifact_sha256":before,
        "static_winners":dict(Counter(r["winner"] for r in rows)),
        "shape_ranges":{k:{"minimum":min(r[k] for r in rows),"maximum":max(r[k] for r in rows),
                            "mean":mean(r[k] for r in rows)} for k in workload_shape(generate_dynamic_workload(2026000000).processes)},
        "stratum_cuts":cuts, "route_controls":route_controls,
        "switches":{"total":len(decisions),"transitions":dict(Counter(e["previous"]+" -> "+e["selected"] for e in decisions)),
                    "median_time":_percentile([e["time"] for e in decisions],.5),
                    "after_all_arrivals":sum(e["after_last_arrival"] for e in decisions),
                    "predicted_margin_mean":mean(e["predicted_costs"][DYNAMIC_POLICY_NAMES.index(e["previous"])]-
                                                   e["predicted_costs"][DYNAMIC_POLICY_NAMES.index(e["selected"])] for e in decisions)},
        "switch_counterfactuals":{"count":len(counterfactuals),
            **{key:mean(c[key] for c in counterfactuals) for key in (
                "predicted_advantage","original_label_advantage","original_fixed_scale_advantage",
                "safe20_mlfq_tail_advantage","selected_is_original_optimal","label_switches_back_before_dwell",
                "label_completed_before_dwell",
                "local_vs_fixed_ranking_disagrees")},
            "worse_than_staying_original_label":sum(c["original_label_advantage"] < -1e-12 for c in counterfactuals),
            "worse_than_staying_safe20_mlfq_tail":sum(c["safe20_mlfq_tail_advantage"] < -1e-12 for c in counterfactuals)},
        "departure_search":departure_summary, "departure_cases":departures,
        "training_state_coverage":{
            "fitted_rows":len(training),"fitted_active_policy_counts":dict(Counter(
                DYNAMIC_POLICY_NAMES[int(float(r["active_policy_index"]))] for r in training)),
            "runtime_reviews":reviews,"runtime_active_policy_counts":dict(runtime_active),
            "runtime_reviews_after_all_arrivals":after_arrivals,
            "outside_fitted_feature_ranges":dict(outside_ranges),
            "feature_importance":dict(zip(DYNAMIC_FEATURE_NAMES,map(float,model.feature_importances_))),
        },
        "probes":{"cases":len(probes),"strict_non_mlfq_wins":sum(p["strictly_beats_mlfq"] for p in probes),
                  "strict_winners":dict(Counter(p["winner"] for p in probes if p["strictly_beats_mlfq"])),
                  "witnesses":witnesses},
    }
    assert before == _hashes(protected), "a protected artifact or production source changed"
    audit["protected_files_unchanged"] = True
    (output/"diagnostics.json").write_text(json.dumps(audit,indent=2),encoding="utf-8")
    print(json.dumps({"static_winners":audit["static_winners"],"controls":route_controls,
                      "departure_search":departure_summary,"switch_audit":audit["switch_counterfactuals"],
                      "stress_probe_winners":audit["probes"]["strict_winners"]},indent=2))


if __name__ == "__main__":
    main()
