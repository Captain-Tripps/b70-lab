"""Per-arm true-token log-loss and top-1 agreement with live on the 63 scorable teacher-forced rows."""
from pathlib import Path
import numpy as np
W = Path(r'<work>')
import sys
d = W / r'experiments\claude-glm-l12-20261115' / (sys.argv[1] if len(sys.argv) > 1 else 'kl')
TAGS = sys.argv[2].split(',') if len(sys.argv) > 2 else ['live', 'esimd', 'joint', 'live2']
val = W / r'experiments\codex-sub768-validation-20261110'
inputs = {'long32k': W / 'long32k.txt', 'code': val / 'code.txt'}
for case, p in inputs.items():
    t = [int(x) for x in p.read_text().replace('\n', ',').split(',') if x.strip()]
    tgt = np.array(t[len(t) - 63:])
    ref = None; out = []
    for tag in TAGS:
        f = d / f'{case}-{tag}-logits.bin'
        if not f.exists():
            continue
        raw = np.fromfile(f, dtype=np.float32)
        a = raw.reshape(64, -1).astype(np.float64)
        if ref is None: ref = a
        m = a[:63].max(1, keepdims=True)
        lsm = a[:63] - (np.log(np.exp(a[:63] - m).sum(1, keepdims=True)) + m)
        nll = -lsm[np.arange(63), tgt]
        hit = (a[:63].argmax(1) == tgt).sum()
        agree = (a.argmax(1) == ref.argmax(1)).sum()
        maxdiff = np.abs(a - ref).max()
        out.append(f'{tag}: NLL={nll.mean():.4f} true_top1={hit}/63 top1_vs_live={agree}/64 max|dlogit|={maxdiff:.3f} same_bytes_as_{TAGS[0]}={raw.tobytes()==ref.astype(np.float32).tobytes()}')
    print(case, f'(N={len(t)})'); [print('  ' + o) for o in out]
