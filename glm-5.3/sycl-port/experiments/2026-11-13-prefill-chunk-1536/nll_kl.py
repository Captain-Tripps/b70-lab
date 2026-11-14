"""Per-arm log-loss of the true next token on the 63 scorable teacher-forced rows (row i predicts t[N-64+i+1])."""
from pathlib import Path
import os
WORK = os.environ["MAYA_WORK"]   # the engine checkout
import numpy as np
d = Path(WORK + r'\experiments\claude-glm-chunk-screen-20261113\kl')
val = Path(WORK + r'\experiments\codex-sub768-validation-20261110')
inputs = {'code': val / 'code.txt', 'records': val / 'records.txt', 'long32k': Path(WORK + r'\long32k.txt')}
for case, p in inputs.items():
    t = [int(x) for x in p.read_text().replace('\n', ',').split(',') if x.strip()]
    tgt = np.array(t[len(t) - 63:])          # rows 0..62 predict these
    out = []
    for tag in ('c768a', 'c768b', 'c1536'):
        f = d / f'{case}-{tag}-logits.bin'
        if not f.exists():
            continue
        a = np.fromfile(f, dtype=np.float32).reshape(64, -1).astype(np.float64)[:63]
        m = a.max(1, keepdims=True)
        lsm = a - (np.log(np.exp(a - m).sum(1, keepdims=True)) + m)
        nll = -lsm[np.arange(63), tgt]
        hit = (a.argmax(1) == tgt).sum()
        out.append(f'{tag}: NLL_mean={nll.mean():.4f} top1_true={hit}/63')
    print(case, f'(N={len(t)})', ' | '.join(out), flush=True)
