from pathlib import Path
import numpy as np
v=Path(r'<work>\experiments\codex-sub768-validation-20261110'); s=Path(r'<work>\experiments\codex-sub768-selective-20261110')
pairs=[('32k diagnostic control',v/'long32k-baseline-logits.bin',s/'long32k-baseline-logits.bin'),('32k recurrent original',v/'long32k-baseline-logits.bin',s/'long32k-kda-logits.bin'),('32k recurrent+dense original',v/'long32k-baseline-logits.bin',s/'long32k-kda-dense-logits.bin'),('8k recurrent+dense original',v/'code-baseline-logits.bin',s/'code-kda-dense-logits.bin')]
for label,x,y in pairs:
 if not y.exists(): print(label+': pending'); continue
 a=np.fromfile(x,dtype=np.float32).reshape(64,-1).astype(np.float64); b=np.fromfile(y,dtype=np.float32).reshape(a.shape).astype(np.float64)
 assert np.isfinite(a).all() and np.isfinite(b).all()
 la=a-(np.log(np.exp(a-a.max(1,keepdims=True)).sum(1,keepdims=True))+a.max(1,keepdims=True));lb=b-(np.log(np.exp(b-b.max(1,keepdims=True)).sum(1,keepdims=True))+b.max(1,keepdims=True))
 kl=(np.exp(la)*(la-lb)).sum(1);same=np.argmax(a,1)==np.argmax(b,1)
 print(f'{label}: top1={same.sum()}/64 KL_mean={kl.mean():.8g} KL_max={kl.max():.8g} max_abs={np.max(np.abs(a-b)):.8g} changed_rows={np.flatnonzero(~same).tolist()} bit_identical={np.array_equal(a,b)}',flush=True)
