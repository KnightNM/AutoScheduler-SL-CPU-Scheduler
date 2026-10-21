"""Inference only: original v5 on previously inspected Azure development labels."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from autoscheduler.azure_generalization import sha,write
from autoscheduler.azure_regression_comparison import metrics
from autoscheduler.azure_v5_retrain import MeanCosts,validate_splits
from autoscheduler.dynamic import DYNAMIC_FEATURE_NAMES,DynamicRouterConfig
from autoscheduler.model import load_model,load_model_metadata


def main():
    model_path=Path('artifacts/dynamic_v5_20261019/policy_cost/model.joblib')
    data_path=Path('artifacts/dynamic_v5_azure_retrained/decision_costs.json')
    out=Path('results/original_v5_azure_prediction_20261020')
    if out.exists():raise ValueError('Refuse overwrite of completed inference evaluation')
    protocol=json.loads(Path('results/dynamic_v5_azure_retrained_20261020/protocol.json').read_text())
    source=json.loads(Path('results/azure_adapted_20261020/protocol.json').read_text())
    rows=json.loads(data_path.read_text());metadata=load_model_metadata(model_path)
    config=DynamicRouterConfig(**metadata['dynamic_config'])
    assert tuple(protocol['features'])==DYNAMIC_FEATURE_NAMES
    assert DynamicRouterConfig(**protocol['config'])==config
    assert sha(model_path)==protocol['protected_sha256'][str(model_path)]
    assert sha(model_path)==source['v5_model_sha256']
    validate_splits(rows,set(source['reserved_holdout_groups']))
    model=load_model(model_path,DYNAMIC_FEATURE_NAMES,expected_dynamic_config=config)
    assert model.policies==tuple(protocol['actions'])==tuple(metadata['action_set'])
    train=[r for r in rows if r['split']=='train'];test=[r for r in rows if r['split']=='test']
    x=np.array([[r['features'][f] for f in DYNAMIC_FEATURE_NAMES] for r in test])
    y=np.array([r['costs'] for r in test]);train_y=np.array([r['costs'] for r in train])
    assert x.shape==(72,19) and y.shape==(72,6) and train_y.shape==(216,6)
    assert np.isfinite(x).all() and np.isfinite(y).all()
    predicted=model.regressor.predict(x);dummy=MeanCosts(train_y).predict(x)
    leaves=model.regressor.tree_;costs=leaves.value[leaves.children_left==-1,:,0]
    winners=np.argmin(costs,axis=1);base=model.policies.index('No Switch')
    admissible=sorted({model.policies[j] for c,j in zip(costs,winners) if c[base]-c[j]>=model.switch_margin})
    result={'model':str(model_path),'model_sha256':sha(model_path),'data_source':str(data_path),
        'data_sha256':sha(data_path),'split':'Previously inspected Azure internal-test development partition',
        'independent_validation':False,'decision_examples':len(test),'provenance_groups':len({r['source_group'] for r in test}),
        'source_groups':sorted({r['source_group'] for r in test}),'feature_names':list(DYNAMIC_FEATURE_NAMES),
        'actions':list(model.policies),'target_units':'Dimensionless frozen-five-static weighted-score deltas versus tuned MLFQ continuation; feasible minimum-dwell excursion then MLFQ.',
        'aggregation':'MAE/RMSE and R2 pooled over 72 x 6 raw cost pairs; no target scaling/masking. Constant per-output R2 is undefined.',
        'metrics':metrics(y,predicted),'dummy_mean_cost':metrics(y,dummy),
        'dummy_reference':{'training_states':len(train),'groups':len({r['source_group'] for r in train}),'fitted':False},
        'training_occurred':False,'holdout_evaluated':False,'model_leaf_admissible_proposals':admissible,
        'limitation':'Azure reconstructed arrivals/wall-clock demand proxies, not measured Linux scheduling. These state trajectories were collected under MLFQ/preemptive exploration, not necessarily the original-model trajectory. No scheduling improvement is inferred.'}
    write(out/'metrics.json',result)
    write(out/'predictions.json',{'actual':y.tolist(),'predicted':predicted.tolist()})
    m=result['metrics'];d=result['dummy_mean_cost']
    (out/'REPORT.md').write_text('# Original v5: saved Azure development labels, inference only\n\n'
        f'Exact artifact `{model_path}`, SHA256 `{sha(model_path)}`. Ordered 19 inputs, six outputs, controller configuration and source-model hash verified against existing labeling protocol. Targets retain original feasible-horizon score-delta interpretation and frozen normalization.\n\n'
        '72 previously inspected internal-test states, six provenance groups; dummy uses means of 216 training states in 18 disjoint groups. No fitting, simulations, final-holdout evaluation or independent-validation claim.\n\n'
        f'Original model: MAE {m["mae"]:.9f}, RMSE {m["rmse"]:.9f}, pooled R² {m["r_squared"]:.6f}.\n\n'
        f'Training-mean dummy: MAE {d["mae"]:.9f}, RMSE {d["rmse"]:.9f}, R² {d["r_squared"]:.6f}.\n\n'
        'Per-output metrics and source hashes: metrics.json; numerical pairs: predictions.json. Zero-head R² is undefined. These figures belong to original v5, not the Azure-retrained tree.\n\n'
        f'Tree inspection: only {admissible} can be argmin and satisfy the unchanged .005 benefit margin. FCFS wins only the all-zero leaf and is denied by the margin; guards can retain/return MLFQ. No RR/FCFS demo is manufactured.\n\n'+result['limitation']+'\n')
    assert sha(model_path)==result['model_sha256'] and sha(data_path)==result['data_sha256']
    print(json.dumps({'metrics':{k:m[k] for k in ['mae','rmse','r_squared']},'dummy':{k:d[k] for k in ['mae','rmse','r_squared']},'admissible':admissible}))


if __name__=='__main__':main()
