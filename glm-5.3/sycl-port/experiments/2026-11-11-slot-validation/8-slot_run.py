import json,os,subprocess,sys,time,urllib.request,threading,ctypes
from pathlib import Path
root=Path(r'<work>\experiments\codex-slot-screen8-20261110');root.mkdir(parents=True,exist_ok=True)
original=json.loads(Path(r'<work>\experiments\codex-20261110\baseline2.json').read_text(encoding='utf8'))
class Mem(ctypes.Structure):
 _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong),('total',ctypes.c_ulonglong),('free',ctypes.c_ulonglong),('totalpage',ctypes.c_ulonglong),('freepage',ctypes.c_ulonglong),('totalvirtual',ctypes.c_ulonglong),('freevirtual',ctypes.c_ulonglong),('freeextended',ctypes.c_ulonglong)]
def sample_memory(stop,path):
 with path.open('w',encoding='utf8') as f:
  while not stop.is_set():
   m=Mem();m.length=ctypes.sizeof(m)
   if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
    f.write(json.dumps({'time':time.time(),'free_bytes':m.free,'total_bytes':m.total,'memory_load_percent':m.load})+'\n');f.flush()
   stop.wait(2)
preflight=r'''$r=Invoke-RestMethod http://100.89.126.50:8080/running -TimeoutSec 5;if (@($r.running).Count -gt 0) {throw 'swap in use'};if (Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(generate|llama-server)\.exe$' }) {throw 'GPU model in use'};$g=@((Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage').CounterSamples | Where-Object { $_.InstanceName -notmatch '0x000159ed' } | ForEach-Object {$_.CookedValue/1GB});if ($g.Count -lt 4 -or ($g | Measure-Object -Maximum).Maximum -gt 1.2) {throw 'GPU not clear'}'''
for arm in ('disk','ram'):
 print('START',arm,flush=True)
 for attempt in range(30):
  check=subprocess.run(['powershell.exe','-NoProfile','-Command',preflight],capture_output=True,timeout=60)
  if check.returncode==0: break
  time.sleep(3)
 else: raise RuntimeError('GPU preflight did not clear')
 cfg=json.loads(json.dumps(original));cfg['log']=str(root/(arm+'-engine.log'));cfg['env']['STRATA_GLM_SLOT_DIR']=str(root/('slots-'+arm))
 if arm=='ram':cfg['env']['STRATA_GLM_SLOT_RAM_GB']='8'
 config=root/(arm+'.json');config.write_text(json.dumps(cfg,indent=2),encoding='utf8')
 env={k:v for k,v in os.environ.items() if not k.upper().startswith(('MAYA_','STRATA_','SYCL_','ZE_','ZES_','UR_','ONEAPI_DEVICE_SELECTOR'))}
 with (root/(arm+'-server.log')).open('wb') as out:
  proc=subprocess.Popen([sys.executable,'-m','serve.server','--engine','strata','--config',str(config),'--host','127.0.0.1','--port','9076'],cwd=r'<work>\maya',env=env,stdout=out,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
  stop=threading.Event();sampler=threading.Thread(target=sample_memory,args=(stop,root/(arm+'-memory.jsonl')),daemon=True);sampler.start()
  try:
   for _ in range(240):
    if proc.poll() is not None:raise RuntimeError(f'{arm} server exited {proc.returncode}')
    try:
     with urllib.request.urlopen('http://127.0.0.1:9076/v1/models',timeout=2) as resp:
      if resp.status==200:break
    except Exception:time.sleep(1)
   else:raise RuntimeError('server did not become ready')
   with (root/(arm+'-bench.jsonl')).open('wb') as log:
    subprocess.run([sys.executable,str(root/'slot_bench.py'),arm],stdout=log,stderr=subprocess.STDOUT,check=True,timeout=1200)
  finally:
   stop.set();sampler.join(timeout=3)
   subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
   try:proc.wait(timeout=20)
   except subprocess.TimeoutExpired:proc.kill()
 print('DONE',arm,flush=True)
print('ALL_DONE',flush=True)
