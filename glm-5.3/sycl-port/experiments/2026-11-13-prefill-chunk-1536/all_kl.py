"""Logit check (768 / 1536 / 768 repeat on code, records, long32k), then the combined 1536 + 64k-checkpoint screen."""
import os
WORK = os.environ["MAYA_WORK"]   # the engine checkout
import subprocess, sys, time, pathlib
root = pathlib.Path(WORK + r'\experiments\claude-glm-chunk-screen-20261113')
kl = root / 'kl'
kl.mkdir(exist_ok=True)
for case in ('code', 'records', 'long32k'):
    for tag, chunk in (('c768a', '768'), ('c1536', '1536'), ('c768b', '768')):
        print('KL', case, tag, time.strftime('%H:%M:%S'), flush=True)
        with open(kl / f'{case}-{tag}.log', 'wb') as out:
            r = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                                str(root / 'kl_chunk.ps1'), '-Case', case, '-Chunk', chunk, '-Tag', tag],
                               stdout=out, stderr=subprocess.STDOUT)
        print('KL_EXIT', case, tag, r.returncode, time.strftime('%H:%M:%S'), flush=True)
        time.sleep(10)
for arm, ckpt, chunk in (('q768-live', 'default', '768'), ('q1536-c64k', '65536', '1536'), ('q768-c64k', '65536', '768')):
    print('ARM', arm, time.strftime('%H:%M:%S'), flush=True)
    r = subprocess.run([sys.executable, str(root / 'screen_chunk.py'), arm, ckpt, 'default', chunk])
    print('ARM_EXIT', arm, r.returncode, time.strftime('%H:%M:%S'), flush=True)
    time.sleep(20)
print('ALL_DONE', time.strftime('%H:%M:%S'), flush=True)
