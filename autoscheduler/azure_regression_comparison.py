"""Fixed prediction-only comparison on saved exact-v5 Azure cost labels."""
import json
from pathlib import Path
import joblib
import numpy as np
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeRegressor

from autoscheduler.azure_generalization import sha, write
from autoscheduler.azure_v5_retrain import validate_splits
from autoscheduler.dynamic import DYNAMIC_FEATURE_NAMES, DynamicRouterConfig
from autoscheduler.model import PolicyCostModel, load_model

SOURCE=Path('results/dynamic_v5_azure_retrained_20261020')
ART=Path('artifacts/dynamic_v5_azure_retrained')
OUT=Path('results/dynamic_v5_azure_prediction_comparison_20261020')
MODEL=Path('artifacts/dynamic_v5_azure_retrained/prediction_selected_experimental.joblib')


def metrics(actual,predicted):
    actual,predicted=np.asarray(actual),np.asarray(predicted)
    if actual.shape!=predicted.shape or actual.ndim!=2 or actual.shape[1]!=6:
        raise ValueError('Exactly six aligned cost outputs required')
    error=predicted-actual
    def values(y,e):
        variance=float(np.var(y));mse=float(np.mean(e**2))
        return {'mae':float(np.mean(abs(e))),'rmse':float(np.sqrt(mse)),
            'r_squared':1-mse/variance if variance>0 else None}
    result=values(actual.ravel(),error.ravel())
    abs_total=np.sum(abs(error));squared_total=np.sum(error**2)
    result['outputs']=[{**values(y,e),'absolute_error_share':float(np.sum(abs(e))/abs_total) if abs_total else 0.,
        'squared_error_share':float(np.sum(e**2)/squared_total) if squared_total else 0.}
        for y,e in zip(actual.T,error.T)]
    nonconstant=np.var(actual,axis=0)>0
    result['nonconstant_outputs']=values(actual[:,nonconstant].ravel(),error[:,nonconstant].ravel()) if any(nonconstant) else None
    return result


def compatible_estimator(estimator,x):
    if np.asarray(estimator.predict(x)).shape!=(len(x),6):raise ValueError('Invalid estimator output shape')
    if not hasattr(estimator,'n_outputs_'):estimator.n_outputs_=6
    return estimator


def distributions(y,rows,actions):
    out={}
    for j,action in enumerate(actions):
        c=y[:,j];q=np.quantile(c,[.25,.5,.75,.95,.99]);iqr=q[2]-q[0]
        largest=np.argsort(abs(c))[-3:][::-1]
        out[action]={'mean':float(np.mean(c)),'variance':float(np.var(c)),
            'min':float(min(c)),'max':float(max(c)),'quantiles_25_50_75_95_99':q.tolist(),
            'exact_zero_count':int(np.sum(c==0)),'near_zero_abs_le_1e_8':int(np.sum(abs(c)<=1e-8)),
            'tukey_outliers':int(np.sum((c<q[0]-1.5*iqr)|(c>q[2]+1.5*iqr))),
            'largest_absolute_targets':[{'workload_id':rows[i]['workload_id'],'source_group':rows[i]['source_group'],
                'time':rows[i]['time'],'cost':float(c[i])} for i in largest]}
    return {'pooled_variance':float(np.var(y)),'outputs':out}


def run():
    if OUT.exists() or MODEL.exists():raise ValueError('Refuse repeated comparison or overwrite')
    protocol=json.loads((SOURCE/'protocol.json').read_text())
    labels=json.loads((ART/'decision_costs.json').read_text())
    reserved=set(json.loads(Path('results/azure_adapted_20261020/protocol.json').read_text())['reserved_holdout_groups'])
    validate_splits(labels,reserved)
    assert len(reserved)==73 and tuple(protocol['features'])==DYNAMIC_FEATURE_NAMES
    actions=tuple(protocol['actions']);assert len(actions)==6
    config=DynamicRouterConfig(**protocol['config'])
    existing=load_model(ART/'model.joblib',DYNAMIC_FEATURE_NAMES,expected_dynamic_config=config)
    protected={str(p):sha(p) for p in [ART/'model.joblib',ART/'decision_costs.json',SOURCE/'results.json',
        SOURCE/'REPORT.md',Path('artifacts/dynamic_v5_20261019/policy_cost/model.joblib')]}
    specs={'regularized_tree':{'max_depth':2,'min_samples_leaf':30,'random_state':9701},
        'ridge':{'alpha':100.0,'feature_scaling':'StandardScaler fitted on training only'},
        'random_forest':{'n_estimators':32,'max_depth':3,'min_samples_leaf':10,'random_state':9701,'n_jobs':1}}
    write(OUT/'protocol.json',{'source_protocol':str(SOURCE/'protocol.json'),'source_data_sha256':sha(ART/'decision_costs.json'),
        'features':list(DYNAMIC_FEATURE_NAMES),'actions':list(actions),'specifications':specs,
        'selection':'Require validation MAE AND RMSE strictly below training-mean dummy; minimize mean of MAE/dummy_MAE and RMSE/dummy_RMSE, then name.',
        'aggregation':'Equal-weight all six raw score-delta outputs, pooled R2 matching historical reports. No target scaling/masking/clipping. Constant-output R2 undefined.',
        'test_scope':'Previously inspected internal development groups, not independent generalization evidence.',
        'holdout_evaluated':False,'protected_sha256':protected})
    splits={s:[r for r in labels if r['split']==s] for s in ['train','validation','test']}
    x={s:np.array([[r['features'][f] for f in DYNAMIC_FEATURE_NAMES] for r in rs]) for s,rs in splits.items()}
    y={s:np.array([r['costs'] for r in rs]) for s,rs in splits.items()}
    assert [len(splits[s]) for s in splits]==[216,72,72]
    assert all(a.shape[1]==19 and np.isfinite(a).all() for a in x.values())
    assert all(a.shape[1]==6 and np.isfinite(a).all() for a in y.values())
    assert existing.policies==actions and existing.switch_margin==.005
    write(OUT/'target_diagnostics.json',{s:distributions(y[s],rs,actions) for s,rs in splits.items()})
    estimators={'existing_tree':existing.regressor,
        'regularized_tree':DecisionTreeRegressor(**specs['regularized_tree']),
        'ridge':make_pipeline(StandardScaler(),Ridge(alpha=100.0)),
        'random_forest':RandomForestRegressor(**specs['random_forest']),
        'dummy_mean':DummyRegressor(strategy='mean')}
    results={}
    for name,estimator in estimators.items():
        if name!='existing_tree':estimator.fit(x['train'],y['train'])
        results[name]={s:metrics(y[s],estimator.predict(x[s])) for s in ['train','validation']}
    dummy=results['dummy_mean']['validation']
    eligible=[n for n,m in results.items() if n!='dummy_mean' and
        all(m['validation'][k]<dummy[k] for k in ['mae','rmse'])]
    chosen=min(eligible,key=lambda n:(sum(results[n]['validation'][k]/dummy[k] for k in ['mae','rmse']),n)) if eligible else None
    write(OUT/'selection.json',{'chosen':chosen,'eligible':eligible,'validation_metrics':results,
        'selected_candidate_test_evaluated':False,'no_hyperparameter_sweep':True})
    if chosen:
        estimator=compatible_estimator(estimators[chosen],x['train'][:2])
        source=joblib.load(ART/'model.joblib')
        model=PolicyCostModel(estimator,actions,existing.switch_margin)
        metadata={**source['metadata'],'experiment':str(OUT),'prediction_candidate':chosen,'diagnostic_only':True}
        joblib.dump({**source,'model':model,'metadata':metadata},MODEL)
        loaded=load_model(MODEL,DYNAMIC_FEATURE_NAMES,expected_dynamic_config=config)
        assert loaded.policies==actions and loaded.switch_margin==.005
        # Only the frozen validation-selected candidate receives new test predictions.
        predictions=loaded.regressor.predict(x['test'])
        results[chosen]['test']=metrics(y['test'],predictions)
        write(OUT/'selected_test_predictions.json',{'predicted':predictions.tolist(),'model_sha256':sha(MODEL)})
    # Previously published test results are shown without re-evaluating competitors.
    historical=json.loads((SOURCE/'prediction_metrics.json').read_text())
    results['existing_tree']['test']=historical['model']['test']
    results['dummy_mean']['test']=historical['mean_cost_dummy']['test']
    assert all(sha(Path(p))==h for p,h in protected.items())
    write(OUT/'results.json',{'chosen':chosen,'metrics':results,'holdout_evaluated':False,
        'model_path':str(MODEL) if chosen else None,'protected_hashes_verified':True,
        'scheduling_evaluated':False,'counts':{s:{'rows':len(rs),'groups':len({r['source_group'] for r in rs})} for s,rs in splits.items()}})
    report=['# Azure v5: fixed prediction-only model comparison','',
        'Saved Azure-proxy score-delta labels; no new labels, scheduler changes or simulations. Same 18/6/6 provenance groups and 216/72/72 states. Test groups were previously inspected; final 73-group holdout untouched.',
        'All candidates retain 19 ordered observed features and six ordered raw cost outputs. Only Ridge scales inputs, using training-only StandardScaler. No target scaling, masking, clipping or imputation. Aggregation matches historical pooled decision-action R²; constant per-output R² is undefined.',
        'Validation selection requires both MAE and RMSE below the training-mean dummy; rank by average relative error. Each new candidate has one fixed configuration (protocol.json).',
        '', 'Model | Split | MAE | RMSE | R²','---|---|---:|---:|---:']
    for name,ms in results.items():
        for split in ['train','validation','test']:
            m=ms.get(split)
            report.append(f'{name} | {split} | '+(' | '.join(f'{m[k]:.9g}' for k in ['mae','rmse','r_squared']) if m else 'Not evaluated | Not evaluated | Not evaluated'))
    report+=['',f'Selected: {chosen or "none; no candidate beats dummy on both validation errors"}. Existing-tree and dummy test metrics are historical; only the selected frozen model received new test predictions.',
        'Target distributions, outlier provenance, per-output errors, nonconstant-head metrics and error shares are saved in target_diagnostics.json/results.json. R² is supporting evidence, never classification accuracy. No scheduling-performance improvement is established.',
        'Original models/artifacts remain unchanged. Any saved candidate is experimental, not promoted.']
    (OUT/'REPORT.md').write_text('\n'.join(report)+'\n')


if __name__=='__main__':run()
