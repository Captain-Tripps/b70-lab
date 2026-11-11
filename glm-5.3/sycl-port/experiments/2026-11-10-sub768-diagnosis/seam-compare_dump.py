from pathlib import Path
import re,numpy as np
r=Path(r'<work>\experiments\codex-sub768-diagnosis-20261110')
a=r/'baseline-dump'; b=r/'sub768-dump'
stages=['attn_norm','dsa_qr','dsa_q','dsa_iq','pf_qabs','pf_ctx','pf_attn','mixer','ffn_norm','pf_shexp','ffn_out']
files=set(p.name for p in a.glob('*.f32')); other=set(p.name for p in b.glob('*.f32'))
print('files baseline',len(files),'candidate',len(other),'missing',sorted(files^other))
for layer in range(45):
 for stage in stages:
  name=f'{stage}-{layer}.f32'
  if name not in files or name not in other: continue
  x=np.fromfile(a/name,dtype=np.float32); y=np.fromfile(b/name,dtype=np.float32)
  if x.shape!=y.shape or not np.isfinite(x).all() or not np.isfinite(y).all(): raise ValueError(name)
  diff=np.abs(x.astype(np.float64)-y.astype(np.float64)); rms=np.sqrt(np.mean(diff**2)); ref=np.sqrt(np.mean(x.astype(np.float64)**2));
  print(f'{name} n={x.size} changed={np.count_nonzero(x.view(np.uint32)!=y.view(np.uint32))} maxabs={diff.max():.9g} rms={rms:.9g} relative_rms={rms/max(ref,1e-30):.9g}')
