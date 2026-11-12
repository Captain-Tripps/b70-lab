import json,os,re,signal,subprocess,sys,time,urllib.request
from pathlib import Path
root=Path('<atlas-home>/experiments/codex-atlas-iq4-20261111');exe=root/'shape_bench'
def slot():
 with urllib.request.urlopen('http://127.0.0.1:9007/slots',timeout=3) as f:x=json.load(f)
 if len(x)!=1:raise RuntimeError('unexpected server slots')
 return x[0]
def mem():return int(subprocess.check_output(['nvidia-smi','--query-gpu=memory.free','--format=csv,noheader,nounits'],text=True,timeout=5).splitlines()[0])
env=os.environ.copy();env['CUDA_VISIBLE_DEVICES']='0';env['LD_LIBRARY_PATH']='<atlas-home>/llama.cpp-v0.9.0/build-cuda/bin'
for rep in range(2):
 for typ in ('iq4_xs','iq4_nl'):
  for m,k in ((17408,5120),(5120,17408)):
   for n in (1,4):
    before=slot()
    if before.get('is_processing') or mem()<700:sys.exit('service busy or GPU memory low; stopping')
    log=root/f'shape-{rep}-{typ}-{m}-{n}-{k}.log'
    with log.open('w') as f:
     p=subprocess.Popen([str(exe),typ,str(m),str(n),str(k)],stdout=f,stderr=subprocess.STDOUT,env=env,start_new_session=True)
     start=time.monotonic();reason=None
     while p.poll() is None:
      time.sleep(.2)
      try:
       now=slot()
       if now.get('is_processing') or now.get('id_task')!=before.get('id_task'):reason='service became active';break
      except Exception:reason='cannot check service';break
      if time.monotonic()-start>90:reason='timeout';break
     if reason:
      os.killpg(p.pid,signal.SIGTERM)
      try:p.wait(timeout=4)
      except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
      print(json.dumps({'type':typ,'m':m,'n':n,'k':k,'rep':rep,'status':'aborted','reason':reason}),flush=True);sys.exit(2)
    txt=log.read_text(errors='replace');lines=re.findall(r'^type=.*$',txt,re.M);after=slot()
    if p.returncode or len(lines)!=1 or after.get('is_processing') or after.get('id_task')!=before.get('id_task'):
     print(json.dumps({'type':typ,'m':m,'n':n,'k':k,'rep':rep,'status':'invalid','rc':p.returncode,'lines':len(lines)}),flush=True);sys.exit(1)
    print(json.dumps({'type':typ,'m':m,'n':n,'k':k,'rep':rep,'status':'ok','result':lines[0]}),flush=True)
