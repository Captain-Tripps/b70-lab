from pathlib import Path
import numpy as np
r=Path(r'<work>\experiments\codex-sub768-diagnosis-20261110')
a=np.fromfile(r/'baseline-logits.bin',dtype=np.float32).reshape(64,-1).astype(np.float64);b=np.fromfile(r/'sub768-logits.bin',dtype=np.float32).reshape(a.shape).astype(np.float64)
la=a-(np.log(np.exp(a-a.max(1,keepdims=True)).sum(1,keepdims=True))+a.max(1,keepdims=True));lb=b-(np.log(np.exp(b-b.max(1,keepdims=True)).sum(1,keepdims=True))+b.max(1,keepdims=True))
kl=(np.exp(la)*(la-lb)).sum(1);same=np.argmax(a,1)==np.argmax(b,1)
print(f'rows=64 vocab={a.shape[1]} top1={same.sum()}/64 KL_mean={kl.mean():.8g} KL_max={kl.max():.8g} max_abs={np.max(np.abs(a-b)):.8g} changed_rows={np.flatnonzero(~same).tolist()}')
