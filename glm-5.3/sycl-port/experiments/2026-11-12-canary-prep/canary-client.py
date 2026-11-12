"""Client-only GLM canary workload. Starts no servers and changes no config.

Run on Zeus with Windows Python, once per arm, only after the operator has
switched the proxy to the intended config. The caller supplies all paths and
the expected SHA-256; logs contain hashes and synthetic tool arguments, not
prompt or generated text. See README.md before invoking.
"""
import argparse, base64, ctypes, hashlib, json, os, subprocess, time, urllib.error, urllib.request
from pathlib import Path

class Mem(ctypes.Structure):
    _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong),('total',ctypes.c_ulonglong),('free',ctypes.c_ulonglong),('totalpage',ctypes.c_ulonglong),('freepage',ctypes.c_ulonglong),('totalvirtual',ctypes.c_ulonglong),('freevirtual',ctypes.c_ulonglong),('freeextended',ctypes.c_ulonglong)]

def memory_free():
    m=Mem();m.length=ctypes.sizeof(m)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):raise RuntimeError('cannot sample host memory')
    return m.free

def get(url,timeout=5):
    with urllib.request.urlopen(url,timeout=timeout) as r:return json.load(r)

def parse_stream(response,start,cancel=False):
    first=None;usage=None;content=[];calls={};events=0;done=False
    for raw in response:
        line=raw.decode('utf8','replace').strip()
        if not line.startswith('data:'):continue
        data=line[5:].strip()
        if data=='[DONE]':done=True;break
        event=json.loads(data);usage=event.get('usage') or usage
        if event.get('error'):raise RuntimeError('server returned an error')
        for choice in event.get('choices',[]):
            if choice.get('finish_reason')=='error':raise RuntimeError('generation ended with an error')
            delta=choice.get('delta') or {};part=(delta.get('content') or '')+(delta.get('reasoning_content') or '')
            if part:
                if first is None:first=time.perf_counter()
                content.append(part);events+=1
            for tc in delta.get('tool_calls') or []:
                if first is None:first=time.perf_counter()
                call=calls.setdefault(tc.get('index',0),{'id':'','type':'function','function':{'name':'','arguments':''}})
                call['id']+=tc.get('id') or '';fn=tc.get('function') or {}
                call['function']['name']+=fn.get('name') or '';call['function']['arguments']+=fn.get('arguments') or ''
        if cancel and events>=8:break
    if first is None or (not cancel and (not done or usage is None)):raise RuntimeError('incomplete stream')
    toolcalls=[calls[k] for k in sorted(calls)]
    canonical={'content':''.join(content),'tool_calls':[{'name':c['function']['name'],'arguments':json.loads(c['function']['arguments'] or '{}')} for c in toolcalls]}
    return first,usage,canonical,toolcalls

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--proxy',required=True,help='Existing llama-swap base URL')
    ap.add_argument('--model',default='glm-5.3-flash-maya-sycl')
    ap.add_argument('--config',type=Path,required=True,help='Live config currently loaded by the proxy')
    ap.add_argument('--expected-config-sha256',required=True)
    ap.add_argument('--fixture',type=Path,required=True,help='Existing long_body.txt')
    ap.add_argument('--media-dir',type=Path,required=True,help='Directory with llama0/llama1 logo fixtures')
    ap.add_argument('--output',type=Path,required=True,help='New JSONL file; must not already exist')
    ap.add_argument('--reference',type=Path,help='Completed baseline JSONL; compare matching request types')
    ap.add_argument('--minutes',type=int,default=60)
    args=ap.parse_args()
    if not 1<=args.minutes<=120:ap.error('--minutes must be between 1 and 120')
    proxy=args.proxy.rstrip('/');model=args.model;source=args.fixture.read_text(encoding='utf8')
    if len(source)<460000:raise RuntimeError('fixture is shorter than expected')
    images=[]
    for name in ('llama0-logo.png','llama1-logo.png'):
        raw=(args.media_dir/name).read_bytes();images.append('data:image/png;base64,'+base64.b64encode(raw).decode('ascii'))
    def check():
        digest=hashlib.sha256(args.config.read_bytes()).hexdigest()
        if digest.lower()!=args.expected_config_sha256.lower():raise RuntimeError('live config hash changed or does not match intended arm')
        if memory_free()<16*1024**3:raise RuntimeError('host available RAM below 16 GiB')
        running=get(proxy+'/running').get('running',[])
        if len(running)!=1 or running[0].get('model')!=model or running[0].get('state')!='ready':raise RuntimeError('expected GLM to be the only ready proxy model')
    def check_engine():
        cfg=json.loads(args.config.read_text(encoding='utf8'))
        ps="Get-CimInstance Win32_Process -Filter \"Name='generate.exe'\" | Select-Object ProcessId,ExecutablePath,CommandLine | ConvertTo-Json -Compress"
        r=subprocess.run(['powershell.exe','-NoProfile','-Command',ps],capture_output=True,text=True,timeout=30,check=True)
        values=json.loads(r.stdout) if r.stdout.strip() else []
        if isinstance(values,dict):values=[values]
        if len(values)!=1 or not values[0].get('ExecutablePath'):raise RuntimeError('expected exactly one inspectable GLM engine')
        if os.path.normcase(values[0]['ExecutablePath'])!=os.path.normcase(cfg['exe']):raise RuntimeError('running engine executable does not match config')
        split=cfg['args'][cfg['args'].index('--layer-split')+1]
        if '--layer-split '+split not in (values[0].get('CommandLine') or ''):raise RuntimeError('running engine split does not match config')
        return values[0]['ProcessId']
    def wait_idle():
        end=time.monotonic()+300
        while time.monotonic()<end:
            check();state=get(proxy+'/upstream/'+model+'/status')
            if not state.get('busy') and not state.get('queued'):return
            time.sleep(2)
        raise RuntimeError('proxy remained busy for five minutes')
    reference={}
    if args.reference:
        for line in args.reference.read_text(encoding='utf8').splitlines():
            row=json.loads(line)
            if row.get('cancelled'):continue
            key=row['label'].split(':')[-1];value=row['output_sha256']
            if key in reference and reference[key]!=value:raise RuntimeError('baseline responses differ for '+key)
            reference[key]=value
        if not reference:raise RuntimeError('empty baseline reference')
        required={'long-prime','long-edit-1','long-edit-2','long-edit-3','short-switch','long-return','append','medium-switch','retry','tool-call','tool-response','image-0','image-1','after-image','truncated'}
        if required-reference.keys():raise RuntimeError('baseline lacks required request types: '+', '.join(sorted(required-reference.keys())))
    check();engine_pid=check_engine();deadline=time.monotonic()+args.minutes*60
    system={'role':'system','content':'Be precise; treat the supplied text as evidence.'}
    def msg(text,question):return [system,{'role':'user','content':text},{'role':'assistant','content':'I have read it.'},{'role':'user','content':question}]
    with args.output.open('x',encoding='utf8') as log:
        def request(label,messages,tools=None,cancel=False):
            wait_idle();check()
            if check_engine()!=engine_pid:raise RuntimeError('GLM engine process changed during test')
            start=time.perf_counter()
            body={'model':model,'messages':messages,'max_tokens':512 if cancel else 64,'temperature':0,'seed':1,'stream':True,'stream_options':{'include_usage':True},'chat_template_kwargs':{'enable_thinking':False}}
            if tools:body['tools']=tools;body['tool_choice']='auto'
            req=urllib.request.Request(proxy+'/v1/chat/completions',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(req,timeout=1800) as response:first,usage,canonical,calls=parse_stream(response,start,cancel)
            row={'label':label,'time':time.time(),'ttft_s':first-start,'elapsed_s':time.perf_counter()-start,'prompt_tokens':(usage or {}).get('prompt_tokens'),'completion_tokens':(usage or {}).get('completion_tokens'),'output_sha256':hashlib.sha256(json.dumps(canonical,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),'tool_calls':canonical['tool_calls'],'cancelled':cancel,'host_available_bytes':memory_free(),'engine_pid_at_start':engine_pid}
            log.write(json.dumps(row,ensure_ascii=False)+'\n');log.flush();print(json.dumps(row),flush=True)
            key=label.split(':')[-1]
            if not cancel and key in reference and row['output_sha256']!=reference[key]:raise RuntimeError('output differs from baseline for '+key)
            if cancel:wait_idle()
            return canonical['content'],calls
        longtext=source[:390000];short=source[390000:415000];medium=source[300000:410000]
        request('long-prime',msg(longtext,'Give a short status for review 0.'))
        cycle=0
        while time.monotonic()<deadline:
            cycle+=1
            for i in (1,2,3):request(f'{cycle}:long-edit-{i}',msg(longtext,f'Give a short status for review {i}.'))
            request(f'{cycle}:short-switch',msg(short,'Summarize this briefly.'))
            branch=msg(longtext,'Give a short status for review 3.')
            answer,_=request(f'{cycle}:long-return',branch)
            request(f'{cycle}:append',branch+[{'role':'assistant','content':answer},{'role':'user','content':'Continue with one more brief observation.'}])
            if cycle%3==1:request(f'{cycle}:medium-switch',msg(medium,'Summarize this briefly.'))
            if cycle%5==1:
                cancel_msg=[{'role':'user','content':'List 100 useful practices for testing software services, with explanations.'}]
                request(f'{cycle}:cancel',cancel_msg,cancel=True);request(f'{cycle}:retry',cancel_msg)
            if cycle%8==1:
                tools=[{'type':'function','function':{'name':'lookup_order','description':'Look up a synthetic order by its ID.','parameters':{'type':'object','properties':{'order_id':{'type':'string'}},'required':['order_id'],'additionalProperties':False}}}]
                m=[{'role':'system','content':'Use the supplied function; do not invent results.'},{'role':'user','content':'Look up synthetic order BB-204 and report its status.'}]
                _,calls=request(f'{cycle}:tool-call',m,tools)
                if not calls:raise RuntimeError('expected tool call was not emitted')
                c=calls[0];m += [{'role':'assistant','content':None,'tool_calls':[c]},{'role':'tool','tool_call_id':c['id'],'content':'{"order_id":"BB-204","status":"packed"}'},{'role':'user','content':'Summarize the returned status.'}]
                request(f'{cycle}:tool-response',m,tools)
            if cycle%12==1:
                for i,image in enumerate(images):
                    m=[{'role':'user','content':[{'type':'text','text':'Describe this image briefly.'},{'type':'image_url','image_url':{'url':image}}]}]
                    request(f'{cycle}:image-{i}',m)
                request(f'{cycle}:after-image',branch)
                request(f'{cycle}:truncated',msg(longtext[:12000],'Give a short status for review 3.'))
        print('CANARY_CLIENT_COMPLETE cycles=',cycle,flush=True)

if __name__=='__main__':main()
