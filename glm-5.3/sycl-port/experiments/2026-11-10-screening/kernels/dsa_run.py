import os, pathlib, subprocess, sys

p = pathlib.Path(r'<work>\experiments\codex-projection-20261110')
exe = p / 'tree' / 'link' / 'dsa_variant_parity.exe'
env = {k: v for k, v in os.environ.items() if not k.upper().startswith(('MAYA_', 'STRATA_', 'SYCL_', 'ZE_', 'ZES_', 'UR_', 'ONEAPI_DEVICE_SELECTOR'))}
env['ONEAPI_DEVICE_SELECTOR'] = 'level_zero:0'
env['ZES_ENABLE_SYSMAN'] = '1'
env['PATH'] = r'<work>\rt-live;C:\Windows\System32;C:\Windows;C:\Program Files (x86)\Intel\oneAPI\mkl\2026.0\bin;C:\Program Files (x86)\Intel\oneAPI\compiler\2026.0\bin'
for label in ('original', 'sx1b4', 'sx2b4', 'rx1b4', 'rx2b4'):
    childenv = env.copy()
    if label != 'original': childenv['STRATA_GLM_DSA_SCORE2'] = label
    try:
        with (p / f'dsa-{label}.out').open('wb') as out, (p / f'dsa-{label}.err').open('wb') as err:
            result = subprocess.run([str(exe), str(p / f'dsa-{label}.bin')], env=childenv, stdout=out, stderr=err, timeout=120)
    except subprocess.TimeoutExpired:
        sys.exit(f'{label} timed out')
    if result.returncode: sys.exit(f'{label} failed: {result.returncode}')
    log = (p / f'dsa-{label}.err').read_text(errors='replace')
    expected = 'on the original kernels' if label == 'original' else f'take-two kernels {label}'
    if expected not in log: sys.exit(f'{label} dispatch not confirmed')
    print(f'{label} PASS dispatch confirmed', flush=True)
