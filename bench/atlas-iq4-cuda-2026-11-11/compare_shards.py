import json, os, re, signal, subprocess, sys, time, urllib.request
from pathlib import Path
root = Path('<atlas-home>/experiments/codex-atlas-iq4-20261111')
base = '<atlas-home>/llama.cpp-v0.9.0/build-cuda/bin'
def slot():
    with urllib.request.urlopen('http://127.0.0.1:9007/slots', timeout=3) as f: slots = json.load(f)
    if len(slots) != 1: raise RuntimeError('unexpected slot count')
    return slots[0]
def free():
    return int(subprocess.check_output(['nvidia-smi','--query-gpu=memory.free','--format=csv,noheader,nounits'], text=True, timeout=5).splitlines()[0])
for rep, arm in enumerate(('base','variant','variant','base','base','variant','variant','base')):
    for m,k in ((2560,17408),(8704,5120),(5120,5120)):
        before = slot()
        if before.get('is_processing') or free() < 700: sys.exit('service busy or GPU memory low')
        env = os.environ.copy(); env['CUDA_VISIBLE_DEVICES']='0'
        env['LD_LIBRARY_PATH'] = (str(root/'variant-2warp') + ':' if arm == 'variant' else '') + base
        log = root / f'compare-{rep}-{arm}-{m}.log'
        with log.open('w') as f:
            p = subprocess.Popen([str(root/'shape_bench'),'iq4_nl',str(m),'4',str(k)], stdout=f, stderr=subprocess.STDOUT, env=env, start_new_session=True)
            start=time.monotonic(); reason=None
            while p.poll() is None:
                time.sleep(.2)
                try:
                    now=slot()
                    if now.get('is_processing') or now.get('id_task') != before.get('id_task'): reason='service became active'; break
                except Exception: reason='cannot check service'; break
                if time.monotonic()-start > 90: reason='timeout'; break
            if reason:
                os.killpg(p.pid,signal.SIGTERM)
                try: p.wait(timeout=4)
                except subprocess.TimeoutExpired: os.killpg(p.pid,signal.SIGKILL); p.wait()
                print(json.dumps({'rep':rep,'arm':arm,'m':m,'status':'aborted','reason':reason}),flush=True); sys.exit(2)
        lines = re.findall(r'^type=.*$',log.read_text(errors='replace'),re.M); after=slot()
        if p.returncode or len(lines)!=1 or after.get('is_processing') or after.get('id_task')!=before.get('id_task'): sys.exit('invalid result')
        print(json.dumps({'rep':rep,'arm':arm,'m':m,'status':'ok','result':lines[0]}),flush=True)
