import json,os,signal,subprocess,sys,time,urllib.request
from pathlib import Path
root=Path('<atlas-home>/experiments/codex-atlas-iq4-20261111')
def slot():
 with urllib.request.urlopen('http://127.0.0.1:9007/slots',timeout=3) as f:x=json.load(f)
 if len(x)!=1:raise RuntimeError('unexpected slots')
 return x[0]
env=os.environ.copy();env['CUDA_VISIBLE_DEVICES']='0';env['LD_LIBRARY_PATH']='<atlas-home>/llama.cpp-v0.9.0/build-cuda/bin'
for typ in ('iq4_xs','iq4_nl'):
 a=slot()
 if a.get('is_processing'):sys.exit('service busy; no trace')
 cmd=['nsys','profile','--trace=cuda','--sample=none','--cpuctxsw=none','--force-overwrite=true','-o',str(root/('trace-'+typ)),str(root/'shape_bench'),typ,'5120','4','17408']
 with (root/('trace-'+typ+'.log')).open('w') as out:
  p=subprocess.Popen(cmd,stdout=out,stderr=subprocess.STDOUT,env=env,start_new_session=True);t=time.monotonic();reason=None
  while p.poll() is None:
   time.sleep(.15)
   try:
    s=slot()
    if s.get('is_processing') or s.get('id_task')!=a.get('id_task'):reason='service active';break
   except Exception:reason='cannot check service';break
   if time.monotonic()-t>35:reason='timeout';break
  if reason:
   os.killpg(p.pid,signal.SIGTERM)
   try:p.wait(timeout=4)
   except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
   sys.exit(reason)
 if p.returncode:sys.exit(f'{typ} trace failed {p.returncode}')
 print(typ,'trace complete',flush=True)
