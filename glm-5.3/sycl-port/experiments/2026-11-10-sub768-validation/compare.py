from pathlib import Path
import numpy as np
root=Path(r'<work>\experiments\codex-sub768-validation-20261110')
for case in ('code','records','long32k'):
    a=np.fromfile(root/f'{case}-baseline-logits.bin',dtype=np.float32).reshape(64,-1).astype(np.float64)
    b=np.fromfile(root/f'{case}-sub768-logits.bin',dtype=np.float32).reshape(a.shape).astype(np.float64)
    if not np.isfinite(a).all() or not np.isfinite(b).all(): raise ValueError('non-finite logits')
    la=a-(np.log(np.exp(a-a.max(axis=1,keepdims=True)).sum(axis=1,keepdims=True))+a.max(axis=1,keepdims=True))
    lb=b-(np.log(np.exp(b-b.max(axis=1,keepdims=True)).sum(axis=1,keepdims=True))+b.max(axis=1,keepdims=True))
    kl=(np.exp(la)*(la-lb)).sum(axis=1)
    same=np.argmax(a,axis=1)==np.argmax(b,axis=1)
    print(f'{case}: rows={len(a)} vocab={a.shape[1]} top1={same.sum()}/{len(a)} KL_mean={kl.mean():.6f} KL_max={kl.max():.6f} max_abs={np.max(np.abs(a-b)):.6f} changed_rows={np.flatnonzero(~same).tolist()}',flush=True)
