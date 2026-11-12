import ctypes, hashlib, json, os, pathlib, subprocess, sys, threading, time, urllib.request

work=pathlib.Path(r'<work>')
root=work/'experiments'/'codex-slot-soak-disk-control-20261111'
root.mkdir(parents=True,exist_ok=True)
seconds=int(os.environ.get('SLOT_SOAK_SECONDS','900'))
original=json.loads((work/'experiments'/'codex-20261110'/'baseline2.json').read_text(encoding='utf8'))
cfg=json.loads(json.dumps(original))
cfg['log']=str(root/'engine.log');cfg['env']['STRATA_GLM_SLOT_DIR']=str(root/'slots')
(root/'ram.json').write_text(json.dumps(cfg,indent=2),encoding='utf8')
preflight=r'''$r=Invoke-RestMethod http://100.89.126.50:8080/running -TimeoutSec 5;if (@($r.running).Count -gt 0) {throw 'swap in use'};if (Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(generate|llama-server)\.exe$' }) {throw 'GPU model in use'};$g=@((Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage').CounterSamples | Where-Object { $_.InstanceName -notmatch '0x000159ed' } | ForEach-Object {$_.CookedValue/1GB});if ($g.Count -lt 4 -or ($g | Measure-Object -Maximum).Maximum -gt 1.2) {throw 'GPU not clear'}'''
subprocess.run(['powershell.exe','-NoProfile','-Command',preflight],check=True,timeout=60)
env={k:v for k,v in os.environ.items() if not k.upper().startswith(('MAYA_','STRATA_','SYCL_','ZE_','ZES_','UR_','ONEAPI_DEVICE_SELECTOR'))}
class Mem(ctypes.Structure):
 _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong),('total',ctypes.c_ulonglong),('free',ctypes.c_ulonglong),('totalpage',ctypes.c_ulonglong),('freepage',ctypes.c_ulonglong),('totalvirtual',ctypes.c_ulonglong),('freevirtual',ctypes.c_ulonglong),('freeextended',ctypes.c_ulonglong)]
def read_json(url,timeout=5):
 with urllib.request.urlopen(url,timeout=timeout) as r:return json.load(r)
done=threading.Event();abort=threading.Event(); abort_reason=[];proc=None
def watcher():
 with (root/'memory.jsonl').open('w',encoding='utf8') as log:
  while not done.is_set():
   m=Mem();m.length=ctypes.sizeof(m)
   if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
    log.write(json.dumps({'time':time.time(),'free_bytes':m.free,'total_bytes':m.total,'load':m.load})+'\n');log.flush()
    if m.free<16*1024**3:abort_reason.append('physical memory below 16 GiB');abort.set()
   try:
    if read_json('http://100.89.126.50:8080/running').get('running'):
     abort_reason.append('proxy started a model');abort.set()
   except Exception:
    abort_reason.append('proxy state unavailable');abort.set()
   if abort.is_set():
    print('ABORT',abort_reason[-1],flush=True)
    if proc and proc.poll() is None:subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    return
   done.wait(2)
source=(work/'long_body.txt').read_text(encoding='utf8')
system={'role':'system','content':'Be precise.'}
def messages(text,question):
 return [system,{'role':'user','content':text},{'role':'assistant','content':'I have read it.'},{'role':'user','content':question}]
longtext=source[:390000]; shorttext=source[390000:415000]; mediumtext=source[300000:410000]
base='http://127.0.0.1:9076'
def req(label,msgs,cancel=False):
 if abort.is_set():raise RuntimeError('watcher aborted')
 body={'model':'glm-5.3-flash-maya-sycl','messages':msgs,'max_tokens':512 if cancel else 64,'temperature':0,'seed':1,'stream':True,'stream_options':{'include_usage':True},'chat_template_kwargs':{'enable_thinking':False}}
 request=urllib.request.Request(base+'/v1/chat/completions',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
 t=time.perf_counter();first=None;usage=None;answer=[];events=0
 with urllib.request.urlopen(request,timeout=1800) as response:
  for raw in response:
   line=raw.decode('utf8','replace').strip()
   if not line.startswith('data:'):continue
   data=line[5:].strip()
   if data=='[DONE]':break
   event=json.loads(data);usage=event.get('usage') or usage
   for ch in event.get('choices',[]):
    delta=ch.get('delta') or {};part=(delta.get('content') or '')+(delta.get('reasoning_content') or '')
    if part:first=first or time.perf_counter();answer.append(part);events+=1
   if cancel and events>=8:break
 if first is None or (not cancel and usage is None):raise RuntimeError('missing content or usage for '+label)
 content=''.join(answer)
 row={'label':label,'time':time.time(),'ttft_s':first-t,'elapsed_s':time.perf_counter()-t,'prompt_tokens':(usage or {}).get('prompt_tokens'),'completion_tokens':(usage or {}).get('completion_tokens'),'answer_sha256':hashlib.sha256(content.encode()).hexdigest(),'cancelled':cancel}
 with (root/'requests.jsonl').open('a',encoding='utf8') as f:f.write(json.dumps(row)+'\n')
 print(json.dumps(row),flush=True)
 if cancel:
  t0=time.monotonic()
  while time.monotonic()-t0<180:
   if abort.is_set():raise RuntimeError('watcher aborted')
   slots=read_json(base+'/slots')
   if not any(x.get('is_processing') for x in slots):break
   time.sleep(1)
  else:raise RuntimeError('cancelled request did not clear within 180 seconds')
  print('CANCEL_CLEARED seconds=',round(time.monotonic()-t0,2),flush=True)
 return content
try:
 with (root/'server.log').open('wb') as out:
  proc=subprocess.Popen([sys.executable,'-m','serve.server','--engine','strata','--config',str(root/'ram.json'),'--host','127.0.0.1','--port','9076'],cwd=str(work/'maya'),env=env,stdout=out,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
  monitor=threading.Thread(target=watcher,daemon=True);monitor.start()
  for _ in range(300):
   if abort.is_set() or proc.poll() is not None:raise RuntimeError('server startup failed or aborted')
   try:
    if read_json(base+'/v1/models',2):break
   except Exception:time.sleep(1)
  else:raise RuntimeError('server startup timeout')
  start=time.monotonic();print('READY seconds=',seconds,flush=True)
  req('long-prime',messages(longtext,'Give a short status for review 0.'))
  cycle=0
  while time.monotonic()-start<seconds:
   cycle+=1
   for n in (1,2,3):req(f'{cycle}:long-edit-{n}',messages(longtext,f'Give a short status for review {n}.'))
   req(f'{cycle}:short-switch',messages(shorttext,'Summarize this briefly.'))
   longmessages=messages(longtext,'Give a short status for review 3.')
   reply=req(f'{cycle}:long-return',longmessages)
   req(f'{cycle}:append',longmessages+[{'role':'assistant','content':reply},{'role':'user','content':'Continue with one more brief observation.'}])
   if cycle%3==0:req(f'{cycle}:medium-switch',messages(mediumtext,'Summarize this briefly.'))
   if cycle%4==0:
    for j in range(2):req(f'{cycle}:extra-{j}',messages(source[415000+j*20000:435000+j*20000],f'Give brief observation {j}.'))
   if cycle%5==0:
    c=[{'role':'user','content':'List 100 useful practices for testing software services, with explanations.'}]
    req(f'{cycle}:cancel',c,True);req(f'{cycle}:retry',c)
   print('CYCLE',cycle,'elapsed_s',round(time.monotonic()-start,1),flush=True)
  print('SOAK_COMPLETE cycles=',cycle,'elapsed_s=',round(time.monotonic()-start,1),flush=True)
finally:
 done.set()
 if proc and proc.poll() is None:subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 if proc:
  try:proc.wait(timeout=20)
  except subprocess.TimeoutExpired:proc.kill()
