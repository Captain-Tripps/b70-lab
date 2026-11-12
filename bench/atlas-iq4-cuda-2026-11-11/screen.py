import json,os,re,signal,subprocess,sys,time,urllib.request
from pathlib import Path
root=Path('<atlas-home>/experiments/codex-atlas-iq4-20261111');root.mkdir(parents=True,exist_ok=True)
exe='<atlas-home>/llama.cpp-v0.9.0/build-cuda/bin/test-backend-ops';lib='<atlas-home>/llama.cpp-v0.9.0/build-cuda/bin'
def slot():
 with urllib.request.urlopen('http://127.0.0.1:9007/slots',timeout=3) as f:
  x=json.load(f)
 if len(x)!=1:raise RuntimeError('unexpected server slot count')
 return x[0]
def mem():
 out=subprocess.check_output(['nvidia-smi','--query-gpu=index,memory.free','--format=csv,noheader,nounits'],text=True,timeout=5)
 return int(out.splitlines()[0].split(',')[1].strip())
env=os.environ.copy();env['CUDA_VISIBLE_DEVICES']='0';env['LD_LIBRARY_PATH']=lib
for rep in range(2):
 for typ in ('iq4_nl','iq4_xs','q4_K','q5_K'):
  for n in (1,2,8,512):
   before=slot()
   if before.get('is_processing') or mem()<700:sys.exit('service busy or GPU memory low; stopping')
   pat=f'type_a={typ},type_b=f32,m=4096,n={n},k=14336,'
   cmd=[exe,'perf','-b','CUDA0','-o','MUL_MAT','-p',pat]
   with (root/f'{rep}-{typ}-{n}.log').open('w') as log:
    p=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT,env=env,start_new_session=True)
    start=time.monotonic();reason=None
    while p.poll() is None:
     time.sleep(.15)
     try:
      now=slot()
      if now.get('is_processing') or now.get('id_task')!=before.get('id_task'):reason='service became active';break
     except Exception:reason='cannot check service';break
     if time.monotonic()-start>25:reason='timeout';break
    if reason:
     os.killpg(p.pid,signal.SIGTERM)
     try:p.wait(timeout=4)
     except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
     print(json.dumps({'type':typ,'n':n,'rep':rep,'status':'aborted','reason':reason}),flush=True);sys.exit(2)
   txt=(root/f'{rep}-{typ}-{n}.log').read_text(errors='replace')
   vals=re.findall(r'([\d.]+)\s+us/run',txt)
   after=slot();clean=(not after.get('is_processing') and after.get('id_task')==before.get('id_task'))
   if p.returncode or len(vals)!=1 or not clean:
    print(json.dumps({'type':typ,'n':n,'rep':rep,'status':'invalid','rc':p.returncode,'matches':len(vals),'clean':clean}),flush=True);sys.exit(1)
   print(json.dumps({'type':typ,'n':n,'rep':rep,'us':float(vals[0]),'status':'ok','id_task':before.get('id_task')}),flush=True)
