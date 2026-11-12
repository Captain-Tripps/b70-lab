import base64, ctypes, hashlib, json, os, pathlib, subprocess, sys, threading, time, urllib.request

WORK=pathlib.Path(os.environ['GLM_WORK'])
ROOT=WORK/'experiments'/'codex-slot-branch-broad-20261112'/sys.argv[1]
ROOT.mkdir(parents=True,exist_ok=True)
keep=sys.argv[1]=='on'
original=json.loads((WORK/'experiments'/'codex-20261110'/'baseline2.json').read_text(encoding='utf8'))
cfg=json.loads(json.dumps(original));cfg['exe']=str(WORK/'experiments'/'codex-slot-branch-20261112'/'tree'/'link'/'generate.exe')
cfg['args'][cfg['args'].index('--layer-split')+1]='14,25,36';cfg['log']=str(ROOT/'engine.log')
cfg['env']['STRATA_GLM_SLOT_DIR']=str(ROOT/'slots');cfg['env']['STRATA_GLM_SLOT_RAM_GB']='12';cfg['env']['STRATA_GLM_SLOTS']='8';cfg['env']['STRATA_GLM_SLOT_KEEP_BRANCH']='1' if keep else '0'
(ROOT/'ram.json').write_text(json.dumps(cfg,indent=2),encoding='utf8')
preflight=r'''$r=Invoke-RestMethod http://100.89.126.50:8080/running -TimeoutSec 5;if (@($r.running).Count -gt 0) {throw 'proxy has model'};if (Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(generate|llama-server)\.exe$' }) {throw 'GPU model in use'};$g=@((Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage').CounterSamples | Where-Object { $_.InstanceName -notmatch '0x000159ed' } | ForEach-Object {$_.CookedValue/1GB});if ($g.Count -lt 4 -or ($g | Measure-Object -Maximum).Maximum -gt 1.2) {throw 'GPU not clear'}'''
subprocess.run(['powershell.exe','-NoProfile','-Command',preflight],check=True,timeout=60)
env={k:v for k,v in os.environ.items() if not k.upper().startswith(('MAYA_','STRATA_','SYCL_','ZE_','ZES_','UR_','ONEAPI_DEVICE_SELECTOR'))}
class Mem(ctypes.Structure):
 _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong),('total',ctypes.c_ulonglong),('free',ctypes.c_ulonglong),('totalpage',ctypes.c_ulonglong),('freepage',ctypes.c_ulonglong),('totalvirtual',ctypes.c_ulonglong),('freevirtual',ctypes.c_ulonglong),('freeextended',ctypes.c_ulonglong)]
def get(url,timeout=5):
 with urllib.request.urlopen(url,timeout=timeout) as r:return json.load(r)
done=threading.Event();abort=threading.Event();why=[];proc=None
def watchdog():
 with (ROOT/'memory.jsonl').open('w',encoding='utf8') as f:
  while not done.is_set():
   m=Mem();m.length=ctypes.sizeof(m)
   if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
    row={'time':time.time(),'free_bytes':m.free,'total_bytes':m.total,'load':m.load}
    try:
     p=subprocess.run(['powershell.exe','-NoProfile','-Command',"Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^generate\\.exe$' } | Select-Object -First 1 ProcessId,WorkingSetSize,PrivatePageCount,PageFileUsage | ConvertTo-Json -Compress"],capture_output=True,text=True,timeout=10)
     row['generate_process']=json.loads(p.stdout) if p.stdout.strip() else None
    except Exception as e:row['process_sample_error']=str(e)
    f.write(json.dumps(row)+'\n');f.flush()
    if m.free<16*1024**3:why.append('host available RAM below 16 GiB');abort.set()
   try:
    if get('http://100.89.126.50:8080/running').get('running'):why.append('proxy started a model');abort.set()
   except Exception:why.append('proxy state unavailable');abort.set()
   if abort.is_set():
    print('ABORT',why[-1],flush=True)
    if proc and proc.poll() is None:subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    return
   done.wait(2)

source=(WORK/'long_body.txt').read_text(encoding='utf8')
# About 8k tokens of common context: enough to expose prompt-prefill cost without approaching context limits.
context=source[:32000];short=source[54000:64000];long2=source[120000:150000]
system={'role':'system','content':'Be precise. Use only the supplied information.'}
def msgs(body,q):return [system,{'role':'user','content':body},{'role':'assistant','content':'I have read it.'},{'role':'user','content':q}]
base='http://127.0.0.1:9076'
def req(label,messages,tools=None):
 if abort.is_set():raise RuntimeError('watchdog aborted')
 body={'model':'glm-5.3-flash-maya-sycl','messages':messages,'max_tokens':96,'temperature':0,'seed':1,'stream':True,'stream_options':{'include_usage':True},'chat_template_kwargs':{'enable_thinking':False}}
 if tools:body['tools']=tools;body['tool_choice']='auto'
 r=urllib.request.Request(base+'/v1/chat/completions',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
 t=time.perf_counter();first=None;usage=None;content=[];calls={}
 with urllib.request.urlopen(r,timeout=1800) as response:
  for raw in response:
   line=raw.decode('utf8','replace').strip()
   if not line.startswith('data:'):continue
   d=line[5:].strip()
   if d=='[DONE]':break
   ev=json.loads(d);usage=ev.get('usage') or usage
   for choice in ev.get('choices',[]):
    delta=choice.get('delta') or {};part=delta.get('content') or ''
    if part:first=first or time.perf_counter();content.append(part)
    for tc in delta.get('tool_calls') or []:
     c=calls.setdefault(tc.get('index',0),{'id':'','type':'function','function':{'name':'','arguments':''}})
     c['id']+=tc.get('id') or '';fn=tc.get('function') or {};c['function']['name']+=fn.get('name') or '';c['function']['arguments']+=fn.get('arguments') or ''
 text=''.join(content);toolcalls=[calls[k] for k in sorted(calls)]
 canonical={'content':text,'tool_calls':[{'name':c['function']['name'],'arguments':json.loads(c['function']['arguments'] or '{}')} for c in toolcalls]}
 row={'label':label,'time':time.time(),'ttft_s':(first-t if first else None),'elapsed_s':time.perf_counter()-t,'prompt_tokens':(usage or {}).get('prompt_tokens'),'completion_tokens':(usage or {}).get('completion_tokens'),'output_sha256':hashlib.sha256(json.dumps(canonical,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),'content_sha256':hashlib.sha256(text.encode()).hexdigest(),'tool_calls':canonical['tool_calls']}
 with (ROOT/'requests.jsonl').open('a',encoding='utf8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
 print(json.dumps(row,ensure_ascii=False),flush=True)
 try:
  slots=get(base+'/slots');(ROOT/'slots-samples.jsonl').open('a',encoding='utf8').write(json.dumps({'label':label,'slots':slots},ensure_ascii=False)+'\n')
 except Exception:pass
 return text,toolcalls

proc=None
try:
 with (ROOT/'server.log').open('wb') as out:
  proc=subprocess.Popen([sys.executable,'-m','serve.server','--engine','strata','--config',str(ROOT/'ram.json'),'--host','127.0.0.1','--port','9076'],cwd=str(WORK/'maya'),env=env,stdout=out,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
  threading.Thread(target=watchdog,daemon=True).start()
  for _ in range(300):
   if abort.is_set() or proc.poll() is not None:raise RuntimeError('startup failed or watchdog aborted')
   try:
    if get(base+'/v1/models',2):break
   except Exception:time.sleep(1)
  else:raise RuntimeError('server startup timeout')
  t0=time.monotonic();print('READY keep_branch=',keep,flush=True)
  # Interleave independent contexts with edits, then revisit both a preserved branch and the same exact request.
  b=msgs(long2,'What are the two main points?')
  req('B-prime',b)
  req('independent-short',msgs(short,'Summarize this in one sentence.'))
  for i in range(10):req(f'A-edit-{i:02d}',msgs(context,f'For edit {i}, identify one relevant point in the source.'))
  req('independent-long',msgs(long2,'Summarize this in one sentence.'))
  req('B-revisit',b);req('B-repeat',b)
  # Real tool-call payload and round trip: record the exact function arguments, replay with matching call id and tool reply.
  tw=[{'type':'function','function':{'name':'lookup_order','description':'Look up a synthetic order by its ID.','parameters':{'type':'object','properties':{'order_id':{'type':'string'}},'required':['order_id'],'additionalProperties':False}}}]
  tm=[{'role':'system','content':'If needed, call the supplied function. Do not invent results.'},{'role':'user','content':'Look up synthetic order BB-204 and report its status.'}]
  _,calls=req('tool-call',tm,tw)
  if calls:
   c=calls[0];toolmsg={'role':'assistant','content':None,'tool_calls':[{'id':c['id'],'type':'function','function':c['function']}]}
   tm2=tm+[toolmsg,{'role':'tool','tool_call_id':c['id'],'content':json.dumps({'order_id':'BB-204','status':'packed'},separators=(',',':'))},{'role':'user','content':'Summarize the returned status in one sentence.'}]
   req('tool-response',tm2,tw)
  else:print('TOOL_CALL_NOT_EMITTED',flush=True)
  # Two distinct image contents; then revisit B and a shorter/truncated version.
  for label,name,prompt in [('image-llama0','llama0-logo.png','Describe the logo briefly.'),('image-llama1','llama1-logo.png','Describe this image briefly.')]:
   raw=(WORK/'maya'/'third_party'/'llama.cpp'/'media'/name).read_bytes();data='data:image/png;base64,'+base64.b64encode(raw).decode('ascii')
   im=[{'role':'user','content':[{'type':'text','text':prompt},{'type':'image_url','image_url':{'url':data}}]}]
   req(label,im)
  req('B-after-images',b);req('truncated-context',msgs(context[:12000],'What are the two main points?'))
  print('SUITE_COMPLETE elapsed_s=',round(time.monotonic()-t0,1),flush=True)
finally:
 done.set()
 if proc and proc.poll() is None:subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 if proc:
  try:proc.wait(timeout=20)
  except subprocess.TimeoutExpired:proc.kill()
