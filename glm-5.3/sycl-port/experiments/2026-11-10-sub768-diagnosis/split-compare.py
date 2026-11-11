from pathlib import Path
import numpy as np
base=Path(r'<work>\experiments\codex-sub768-validation-20261110'); diag=Path(r'<work>\experiments\codex-sub768-splitout-20261110')
pairs=[('live-baseline vs diagnostic-baseline',base/'long32k-baseline-logits.bin',diag/'baseline-logits.bin'),('live-baseline vs split-out candidate',base/'long32k-baseline-logits.bin',diag/'sub768-logits.bin'),('ordinary-768 vs split-out candidate',base/'long32k-sub768-logits.bin',diag/'sub768-logits.bin')]
for label,x,y in pairs:
 a=np.fromfile(x,dtype=np.float32).reshape(64,-1).astype(np.float64); b=np.fromfile(y,dtype=np.float32).reshape(a.shape).astype(np.float64)
 assert np.isfinite(a).all() and np.isfinite(b).all()
 la=a-(np.log(np.exp(a-a.max(1,keepdims=True)).sum(1,keepdims=True))+a.max(1,keepdims=True));lb=b-(np.log(np.exp(b-b.max(1,keepdims=True)).sum(1,keepdims=True))+b.max(1,keepdims=True))
 kl=(np.exp(la)*(la-lb)).sum(1);same=np.argmax(a,1)==np.argmax(b,1)
 print(f'{label}: top1={same.sum()}/64 KL_mean={kl.mean():.8g} KL_max={kl.max():.8g} max_abs={np.max(np.abs(a-b)):.8g} changed_rows={np.flatnonzero(~same).tolist()} bit_identical={np.array_equal(a,b)}')
