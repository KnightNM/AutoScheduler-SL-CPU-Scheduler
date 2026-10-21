"""Read-only, inference-only reproduction of both v5 Azure regression results."""
import json
import os
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
# Make the requested plain-python command use the project's installed dependencies.
project_python = ROOT / '.venv/bin/python'
if project_python.is_file() and Path(sys.prefix).resolve() != (ROOT / '.venv').resolve():
    os.execv(str(project_python), [str(project_python), str(Path(__file__).resolve()), *sys.argv[1:]])
sys.path.insert(0, str(ROOT))


def main():
    started = perf_counter()
    import numpy as np
    from autoscheduler.azure_generalization import sha
    from autoscheduler.azure_regression_comparison import metrics
    from autoscheduler.azure_v5_retrain import MeanCosts, validate_splits
    from autoscheduler.dynamic import DYNAMIC_FEATURE_NAMES, DynamicRouterConfig
    from autoscheduler.model import load_model

    def read(path):
        return json.loads((ROOT / path).read_text())

    research = 'results/dynamic_v5_azure_retrained_20261020/'
    protocol = read(research + 'protocol.json')
    original_saved = read('results/original_v5_azure_prediction_20261020/metrics.json')
    retrained_saved = read(research + 'prediction_metrics.json')
    models = [
        ('Original Dynamic ML v5', 'artifacts/dynamic_v5_20261019/policy_cost/model.joblib',
         original_saved['model_sha256'], original_saved['metrics']),
        ('Azure-Retrained v5', 'artifacts/dynamic_v5_azure_retrained/model.joblib',
         read(research + 'frozen_model.json')['sha256'], retrained_saved['model']['test']),
    ]
    data_path = 'artifacts/dynamic_v5_azure_retrained/decision_costs.json'
    protected = {p: sha(ROOT / p) for p in [data_path, *(m[1] for m in models)]}
    if protected[data_path] != original_saved['data_sha256']:
        raise ValueError('Saved labeled dataset hash differs from the verified evaluation.')
    if tuple(protocol['features']) != DYNAMIC_FEATURE_NAMES:
        raise ValueError('Labeled feature order differs from the current v5 contract.')
    config = DynamicRouterConfig(**protocol['config'])
    rows = read(data_path)
    reserved = read('results/azure_adapted_20261020/protocol.json')['reserved_holdout_groups']
    validate_splits(rows, set(reserved))
    train = [r for r in rows if r['split'] == 'train']
    test = [r for r in rows if r['split'] == 'test']
    X_test = np.array([[r['features'][f] for f in DYNAMIC_FEATURE_NAMES] for r in test])
    y_test = np.array([r['costs'] for r in test])
    y_train = np.array([r['costs'] for r in train])
    groups = len({r['source_group'] for r in test})
    if X_test.shape != (72, 19) or y_test.shape != (72, 6) or y_train.shape != (216, 6) or groups != 6:
        raise ValueError('Expected 72 test states/six groups and 216 training-reference states.')
    if not all(np.isfinite(a).all() for a in [X_test, y_test, y_train]):
        raise ValueError('Nonfinite features or cost labels; no imputation is performed.')

    def evaluate(model, saved):
        predictions = model.predict(X_test)
        calculated = metrics(y_test, predictions)
        # Compare only after fresh inference and calculation; saved scores never supply output.
        keys = ('mae', 'rmse', 'r_squared')
        np.testing.assert_allclose([calculated[k] for k in keys], [saved[k] for k in keys],
                                   rtol=1e-9, atol=1e-12, err_msg='Fresh metrics differ from saved evaluation')
        return calculated

    results = []
    for name, path, expected_hash, saved in models:
        if protected[path] != expected_hash:
            raise ValueError(f'Unexpected model artifact hash: {path}')
        router_model = load_model(ROOT / path, DYNAMIC_FEATURE_NAMES, expected_dynamic_config=config)
        if router_model.policies != tuple(protocol['actions']):
            raise ValueError(f'Six-output target ordering is incompatible: {path}')
        # PolicyCostModel.predict returns policy names; its fitted regressor predicts the six costs.
        results.append((name, evaluate(router_model.regressor, saved)))
    results.append(('Mean-Cost Baseline', evaluate(MeanCosts(y_train), retrained_saved['mean_cost_dummy']['test'])))
    if any(sha(ROOT / p) != h for p, h in protected.items()):
        raise ValueError('A source artifact changed during evaluation.')

    print('Dataset: Azure Functions 2019 — reconstructed CPU scheduling workloads')
    print('Evaluation: Previously inspected development test data, not independent validation')
    print(f'Split: internal test | Decision states: {len(test)} | Provenance groups: {groups}')
    print(f'Labeled data: {data_path}')
    for name, path, _, _ in models:
        print(f'{name}: {path}')
    print('Dummy: per-output means from 216 saved training states in 18 disjoint groups; no fit.')
    print('Targets: dimensionless weighted-score deltas relative to MLFQ continuation.')
    print('Aggregation: pooled 72 × 6 cost pairs; unchanged target scaling, no masking.')
    print('R² measures regression fit, not classification accuracy. Negative values indicate poor fit.\n')
    print(f'{"Model":<27} {"MAE":>13} {"RMSE":>13} {"R²":>15}')
    print('-' * 71)
    for name, m in results:
        print(f'{name:<27} {m["mae"]:13.9f} {m["rmse"]:13.9f} {m["r_squared"]:15.6f}')
    print('\nFresh metrics match saved evaluations within floating-point tolerance.')
    print('Models loaded from saved artifacts; no training performed.')
    print('No scheduling simulations or final-holdout evaluation performed.')
    print(f'Runtime: {perf_counter() - started:.3f} seconds')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ImportError, ValueError, KeyError, AssertionError) as error:
        sys.exit(f'Evaluation unavailable: {error}')
