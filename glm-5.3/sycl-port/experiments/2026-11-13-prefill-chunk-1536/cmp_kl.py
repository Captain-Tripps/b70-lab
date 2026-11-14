import os
WORK = os.environ["MAYA_WORK"]   # the engine checkout
from pathlib import Path
import numpy as np
d = Path(WORK + r'\experiments\claude-glm-chunk-screen-20261113\kl')


def load(p):
    a = np.fromfile(p, dtype=np.float32)
    return a.reshape(64, -1).astype(np.float64)


def lsm(a):
    m = a.max(axis=1, keepdims=True)
    return a - (np.log(np.exp(a - m).sum(axis=1, keepdims=True)) + m)


for case in ('code', 'records', 'long32k'):
    for x, y in (('c768a', 'c768b'), ('c768a', 'c1536'), ('c768b', 'c1536')):
        try:
            a = load(d / f'{case}-{x}-logits.bin'); b = load(d / f'{case}-{y}-logits.bin')
        except Exception as e:
            print(case, x, y, 'MISSING', e); continue
        if not np.isfinite(a).all() or not np.isfinite(b).all():
            print(case, x, y, 'NON-FINITE'); continue
        la, lb = lsm(a), lsm(b)
        kl = (np.exp(la) * (la - lb)).sum(axis=1)
        same = a.argmax(1) == b.argmax(1)
        print(f'{case} {x} vs {y}: top1={same.sum()}/64 KL_mean={kl.mean():.6f} KL_max={kl.max():.6f} '
              f'max_abs={np.abs(a - b).max():.4f} changed={np.flatnonzero(~same).tolist()}', flush=True)
