import json,time,urllib.request
from pathlib import Path
root=Path(r'<work>\experiments\codex-promptmemo-20261110'); src=Path(r'<work>\long_body.txt').read_text(encoding='utf8')[:390000]
base=[{'role':'system','content':'Be precise.'},{'role':'user','content':src},{'role':'assistant','content':'I have read it.'}]
def run(mode,tag,turn):
 (root/'mode.txt').write_text(mode,encoding='ascii')
 body={'model':'glm-5.3-flash-maya-sycl','messages':base+[{'role':'user','content':f'Give a short status for review {turn}.'}],'max_tokens':4,'temperature':0,'seed':1,'stream':True,'stream_options':{'include_usage':True},'chat_template_kwargs':{'enable_thinking':False}}
 req=urllib.request.Request('http://127.0.0.1:9075/v1/chat/completions',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
 t=time.perf_counter();first=None;last=None;usage=None;answer=[]
 with urllib.request.urlopen(req,timeout=1800) as r:
  for line in r:
   line=line.decode('utf8','replace').strip()
   if not line.startswith('data:'):continue
   data=line[5:].strip()
   if data=='[DONE]':break
   ev=json.loads(data);usage=ev.get('usage') or usage
   for choice in ev.get('choices',[]):
    delta=choice.get('delta') or {}; part=(delta.get('content') or '')+(delta.get('reasoning_content') or '')
    if part:
     now=time.perf_counter();first=first or now;last=now;answer.append(part)
 if first is None or usage is None:raise RuntimeError('missing response')
 print(json.dumps({'tag':tag,'mode':mode,'prompt_tokens':usage.get('prompt_tokens'),'completion_tokens':usage.get('completion_tokens'),'ttft_s':first-t,'elapsed_s':time.perf_counter()-t,'answer':''.join(answer)}),flush=True)
run('0','prime',0)
run('1','warm-memo',1)
for i,mode in enumerate(('0','1','1','0','1','0')):run(mode,'measured-'+str(i+1),i+2)
