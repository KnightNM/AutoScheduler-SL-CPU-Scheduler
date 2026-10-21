"""Shared paths, schemas, and serialization for the isolated Azure pipeline."""
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(REPO))
KEY = ['HashOwner', 'HashApp', 'HashFunction']
MINUTES = [str(i) for i in range(1, 1441)]
STATS = ['Average', 'Count', 'Minimum', 'Maximum'] + [
    f'percentile_Average_{i}' for i in [0, 1, 25, 50, 75, 99, 100]]
INV_COLUMNS = KEY + ['Trigger'] + MINUTES
DUR_COLUMNS = KEY + STATS


def dump(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def day_of(path):
    match = re.search(r'\.d(\d+)\.csv$', Path(path).name)
    if not match:
        raise ValueError(f'Cannot identify day: {path}')
    return int(match[1])


def append_csv(frame, path):
    frame.to_csv(path, index=False, mode='a', header=not Path(path).exists(),
                 na_rep='', float_format='%.17g', chunksize=1024)


def summary(values):
    import numpy as np
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if not len(values):
        return {'n': 0}
    return {'n': int(len(values)), 'min': float(values.min()), 'mean': float(values.mean()),
            'p50': float(np.quantile(values, .5)), 'p95': float(np.quantile(values, .95)),
            'p99': float(np.quantile(values, .99)), 'max': float(values.max())}


def source_seed(source, seed, tag):
    import hashlib
    text = ':'.join(map(str,[seed,source['day'],*(source[k] for k in KEY),source['start_minute'],tag]))
    return int.from_bytes(hashlib.sha256(text.encode()).digest(),'big')


def snapshot_offsets(source, seed):
    """Joint order statistics for K consecutive ranks among N uniform arrivals.

    Dirichlet gaps avoid expanding N invocations. Flooring gives integer ms.
    These are conditional uniform reconstructions, never observed subminute traces.
    """
    import numpy as np
    index = source['snapshot']['minute_index']
    count = int(source['counts'][index])
    selected = int(source['snapshot']['selected_count'])
    if not 0 < selected <= count:
        raise ValueError('Invalid snapshot size')
    rng = np.random.default_rng(source_seed(source,seed,'snapshot'))
    rank = int(rng.integers(0,count-selected+1))
    alpha = np.r_[rank+1,np.ones(selected-1),count-rank-selected+1]
    offsets = np.floor(np.cumsum(rng.dirichlet(alpha))[:selected]*60000).astype(int)
    return [(rank+i+1,int(offset)) for i,offset in enumerate(offsets)]
