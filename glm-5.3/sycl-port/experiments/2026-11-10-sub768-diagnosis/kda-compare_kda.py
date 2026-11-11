from pathlib import Path
import numpy as np
r=Path(r'<work>\experiments\codex-sub768-kda-20261110')
for name in ['kda_q-0.f32','kda_k-0.f32','kda_v-0.f32','kda_fa-0.f32','kda_ga-0.f32','kda_beta-0.f32','kda_cq-0.f32','kda_ck-0.f32','kda_cv-0.f32','kda_g1-0.f32','kda_g2-0.f32','kda_out16-0.f16','mixer-0.f32']:
 dt=np.float16 if name.endswith('f16') else np.float32
 a=np.fromfile(r/'baseline-dump'/name,dtype=dt); b=np.fromfile(r/'sub768-dump'/name,dtype=dt)
 assert a.shape==b.shape and np.isfinite(a).all() and np.isfinite(b).all()
 diff=np.abs(a.astype(np.float64)-b.astype(np.float64)); rms=np.sqrt(np.mean(diff**2)); ref=np.sqrt(np.mean(a.astype(np.float64)**2))
 print(f'{name} count={a.size} unequal={np.count_nonzero(a!=b)} maxabs={diff.max():.9g} rms={rms:.9g} rel_rms={rms/max(ref,1e-30):.9g}')
