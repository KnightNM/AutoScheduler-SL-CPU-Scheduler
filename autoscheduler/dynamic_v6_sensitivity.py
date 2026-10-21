"""Fixed, post-audit explanation only: no fitting, selection, or promotion."""
import json
from pathlib import Path
import subprocess
import sys

from autoscheduler.dynamic_training import prepare_validation
from autoscheduler.dynamic import DynamicRouterConfig
from autoscheduler.dynamic_v5_experiment import paired, acceptance
from autoscheduler.dynamic_v3_experiment import _write, _hash


def main():
    output = Path("results/dynamic_v6_20261019/sensitivity.json")
    if output.exists():
        raise ValueError("sensitivity results already exist; do not overwrite")
    summary = json.loads(output.with_name("research_summary.json").read_text())
    cases, _ = prepare_validation(240, 10603, DynamicRouterConfig(**summary["config"]), development="v4")
    payload = [{"seed": w.seed, "family": w.family, "processes": [
        {key: getattr(p, key) for key in ("pid", "arrival_time", "burst_time", "priority", "cpu_bursts", "io_bursts")}
        for p in w.processes]} for w, _, _ in cases]
    # This deliberately intervenes on the archived guard in a disposable worker.
    # Model, predictions, MLFQ parameters and artifact metadata are untouched.
    code = '''
import sys,json
sys.path.insert(0,sys.argv[1])
import autoscheduler.dynamic as dynamic
from autoscheduler.model import load_model,load_model_metadata
from autoscheduler.evaluation import compare_algorithms,score_result_against_reference
from autoscheduler.fairness import aggregate_fairness
from simulator.process import Process
from simulator.simulator import run_simulation
from scheduler.mlfq import mlfq
model_path="artifacts/dynamic_v5_20261019/policy_cost/model.joblib"
model=load_model(model_path,dynamic.DYNAMIC_FEATURE_NAMES)
config=dynamic.DynamicRouterConfig(**load_model_metadata(model_path)["dynamic_config"])
original=dynamic._tail_action
def guard(features,active,selected,config):
 chosen,reason=original(features,active,selected,config)
 if reason is None and active=="MLFQ" and selected!="MLFQ" and not features["first_service_ready_count"] and features["arrival_quiet_ticks"]<2*config.epoch_ticks*config.dwell_epochs:
  return active,"arrival_risk"
 return chosen,reason
dynamic._tail_action=guard
rows=[];latencies=[]
for item in json.load(sys.stdin):
 jobs=[Process(**p) for p in item["processes"]]
 router=dynamic.run_dynamic(jobs,model,config)
 latencies.extend(d.transition_ms for d in router.decisions)
 static=run_simulation("Frozen v5 Tuned MLFQ",mlfq,jobs,quanta=config.mlfq_quanta,aging_threshold=config.mlfq_aging_threshold)
 refs=compare_algorithms(jobs)
 for name,result in (("V5 plus v6 guard",router.simulation),("Frozen v5 Tuned MLFQ",static)):
  rows.append(dict(seed=item["seed"],family=item["family"],policy=name,
   score=score_result_against_reference(result,refs),
   p95_response=dynamic._percentile([m.response_time for m in result.process_metrics],.95),
   worst_response=max(m.response_time for m in result.process_metrics),
   starvation=aggregate_fairness(result.process_metrics)["starvation_count"],
   switches=sum(d.accepted for d in router.decisions) if result is router.simulation else 0,
   decision_p99_ms=router.transition_p99_ms if result is router.simulation else None))
json.dump(dict(rows=rows,pooled_p99_ms=dynamic._percentile(latencies,.99)),sys.stdout)
'''
    archive = Path("artifacts/dynamic_v6_20261019/before_source")
    replay = subprocess.run([sys.executable, "-c", code, str(archive.resolve())],
        input=json.dumps(payload), text=True, capture_output=True, check=True)
    sensitivity = json.loads(replay.stdout)
    previous = json.loads(output.with_name("v5_replay.json").read_text())["rows"]
    import csv
    with (output.parent / "audit/workloads.csv").open() as stream:
        current = [{k: float(v) if k not in ("policy", "family") and v else v for k, v in row.items()}
                   for row in csv.DictReader(stream)]
    frozen = [r for r in sensitivity["rows"] if r["policy"] == "Frozen v5 Tuned MLFQ"]
    records = sensitivity["rows"] + previous + [r for r in current if r["policy"] in ("policy_cost", "Round Robin")]
    comparisons = {}
    for name in ("V5 plus v6 guard", "policy_cost", "Dynamic v5"):
        rows = [r for r in records if r["policy"] == name]
        comparisons[name] = {"against_frozen_v5_static": paired(rows, frozen), "against_v5": paired(rows, previous),
            "against_frozen_v5_static_gates": acceptance((paired(rows, frozen), paired(rows,
                [r for r in records if r["policy"] == "Round Robin"])), max(r["decision_p99_ms"] for r in rows)),
            "by_family": {f: paired([r for r in rows if r["family"] == f],
                                    [r for r in frozen if r["family"] == f]) for f in sorted({r["family"] for r in rows})}}
    _write(output, {"purpose": "Post-audit attribution and fixed-baseline sensitivity only; no selection or retuning",
        "intervention": "Archived v5 model and (1,2,4)/40 MLFQ unchanged; only guard quiet window doubled in disposable process",
        "source_sha256": _hash(Path(__file__)), "rows": sensitivity["rows"],
        "ablation_pooled_p99_ms": sensitivity["pooled_p99_ms"], "comparisons": comparisons})


if __name__ == "__main__":
    main()
