from pathlib import Path
import numpy as np
root=Path(r'<work>\experiments\codex-sub768-validation-20261110')
for x,y in [('baseline','repeat-baseline'),('sub768','repeat-sub768'),('repeat-baseline','repeat-sub768')]:
 a=np.fromfile(root/f'long32k-{x}-logits.bin',dtype=np.float32).reshape(64,-1).astype(np.float64)
 b=np.fromfile(root/f'long32k-{y}-logits.bin',dtype=np.float32).reshape(a.shape).astype(np.float64)
 if not np.isfinite(a).all() or not np.isfinite(b).all(): raise ValueError('non-finite logits')
 la=a-(np.log(np.exp(a-a.max(axis=1,keepdims=True)).sum(axis=1,keepdims=True))+a.max(axis=1,keepdims=True))
 lb=b-(np.log(np.exp(b-b.max(axis=1,keepdims=True)).sum(axis=1,keepdims=True))+b.max(axis=1,keepdims=True))
 kl=(np.exp(la)*(la-lb)).sum(axis=1); same=np.argmax(a,axis=1)==np.argmax(b,axis=1)
 print(f'{x} vs {y}: top1={same.sum()}/64 KL_mean={kl.mean():.8f} KL_max={kl.max():.8f} max_abs={np.max(np.abs(a-b)):.8f} changed_rows={np.flatnonzero(~same).tolist()} bit_identical={np.array_equal(a,b)}',flush=True)
