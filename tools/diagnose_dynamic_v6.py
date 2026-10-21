"""Replay the three previously identified v5 failures; never fit or select a model."""
import argparse
import json
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    code = '''
import json,sys
sys.path.insert(0,sys.argv[1])
from autoscheduler.development_workloads import generate_development_workload_v4
from autoscheduler.dynamic import DYNAMIC_FEATURE_NAMES,DynamicRouterConfig,run_dynamic,_percentile
from autoscheduler.model import load_model,load_model_metadata
from scheduler.mlfq import mlfq
from simulator.simulator import run_simulation
model_path="artifacts/dynamic_v5_20261019/policy_cost/model.joblib"
model=load_model(model_path,DYNAMIC_FEATURE_NAMES)
config=DynamicRouterConfig(**load_model_metadata(model_path)["dynamic_config"])
output=[]
for residual in json.load(open("results/dynamic_v5_20261019/residual_diagnosis.json")):
 w=generate_development_workload_v4(residual["seed"],residual["family"])
 result=run_dynamic(w.processes,model,config)
 baseline=run_simulation("Tuned MLFQ",mlfq,w.processes,quanta=config.mlfq_quanta,aging_threshold=config.mlfq_aging_threshold)
 cutoff=_percentile([m.response_time for m in baseline.process_metrics],.95)
 base={m.pid:m for m in baseline.process_metrics}
 decisions=[dict(time=d.time,selected=d.selected,active=d.active,accepted=d.accepted,reason=d.reason,features=d.features) for d in result.decisions]
 witnesses=[]
 for original in residual["decisions"]:
  if not original["accepted"] or original["active"]=="MLFQ":continue
  t=original["time"]
  history=sorted(set(p.arrival_time for p in w.processes if p.arrival_time<=t))
  witnesses.append(dict(departure=t,observed_arrival_timestamps=history,
    observed_ready_count=original["features"]["ready_count"],
    observed_first_service_ready_count=original["features"]["first_service_ready_count"],
    quiet_ticks=original["features"]["arrival_quiet_ticks"],
    v6_would_block=original["features"]["arrival_quiet_ticks"]<2*config.epoch_ticks*config.dwell_epochs))
 jobs=[dict(pid=m.pid,arrival=m.arrival_time,first_dispatch=m.arrival_time+m.response_time,
   response=m.response_time,baseline_first_dispatch=base[m.pid].arrival_time+base[m.pid].response_time,
   baseline_response=base[m.pid].response_time,crosses_baseline_p95=m.response_time>cutoff) for m in result.simulation.process_metrics]
 p95=_percentile([m.response_time for m in result.simulation.process_metrics],.95)
 assert abs(p95-residual["p95"])<1e-9
 output.append(dict(seed=w.seed,family=w.family,p95=p95,baseline_p95=cutoff,
   witnesses=witnesses,processes=jobs,decisions=decisions,
   dynamic_timeline=result.simulation.timeline,baseline_timeline=baseline.timeline))
json.dump(output,sys.stdout)
'''
    replay = subprocess.run([sys.executable, "-c", code,
        str(Path("artifacts/dynamic_v6_20261019/before_source").resolve())],
        capture_output=True, text=True, check=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(json.loads(replay.stdout), indent=2) + "\n")


if __name__ == "__main__":
    main()
