import os, pathlib, subprocess, sys
import numpy as np

root = pathlib.Path(r'<work>\experiments')
outdir = root / 'codex-xmx-bn64-20261110'
env = {k: v for k, v in os.environ.items() if not k.upper().startswith(('MAYA_', 'STRATA_', 'SYCL_', 'ZE_', 'ZES_', 'UR_', 'ONEAPI_DEVICE_SELECTOR'))}
env['ONEAPI_DEVICE_SELECTOR'] = 'level_zero:0'
env['ZES_ENABLE_SYSMAN'] = '1'
env['PATH'] = r'<work>\rt-live;C:\Windows\System32;C:\Windows;C:\Program Files (x86)\Intel\oneAPI\mkl\2026.0\bin;C:\Program Files (x86)\Intel\oneAPI\compiler\2026.0\bin'
arms = [('control', 'codex-xmx-20261110'), ('bn64', 'codex-xmx-bn64-20261110')]
for label, folder in arms:
    exe = root / folder / 'tree' / 'link' / 'xmx_bn_parity.exe'
    try:
        with (outdir / f'fixture-{label}.out').open('wb') as out, (outdir / f'fixture-{label}.err').open('wb') as err:
            r = subprocess.run([str(exe), str(outdir / f'fixture-{label}.bin')], env=env, stdout=out, stderr=err, timeout=120)
    except subprocess.TimeoutExpired:
        sys.exit(f'{label} timed out')
    if r.returncode: sys.exit(f'{label} failed: {r.returncode}')
    print(label, 'fixture completed', flush=True)
a = np.fromfile(outdir / 'fixture-control.bin', dtype=np.float32)
b = np.fromfile(outdir / 'fixture-bn64.bin', dtype=np.float32)
if a.shape != b.shape or not np.isfinite(a).all() or not np.isfinite(b).all(): sys.exit('shape or finite check failed')
different = np.count_nonzero(a.view(np.uint32) != b.view(np.uint32))
print(f'values={a.size} bit_differences={different} max_abs={np.max(np.abs(a-b)):.9g}', flush=True)
