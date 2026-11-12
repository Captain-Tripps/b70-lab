import json,sys,time,urllib.request
from pathlib import Path
root=Path(r'<work>\experiments\codex-slot-screen8-20261110');arm=sys.argv[1]
source=Path(r'<work>\long_body.txt').read_text(encoding='utf8')
base=[{'role':'system','content':'Be precise.'},{'role':'user','content':source[:25000]},{'role':'assistant','content':'I have read it.'}]
def req(label,messages):
 body={'model':'glm-5.3-flash-maya-sycl','messages':messages,'max_tokens':64,'temperature':0,'seed':1,'stream':True,'stream_options':{'include_usage':True},'chat_template_kwargs':{'enable_thinking':False}}
 request=urllib.request.Request('http://127.0.0.1:9076/v1/chat/completions',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
 t=time.perf_counter();first=None;usage=None;answer=[]
 with urllib.request.urlopen(request,timeout=1800) as response:
  for raw in response:
   line=raw.decode('utf8','replace').strip()
   if not line.startswith('data:'): continue
   data=line[5:].strip()
   if data=='[DONE]':break
   event=json.loads(data);usage=event.get('usage') or usage
   for ch in event.get('choices',[]):
    delta=ch.get('delta') or {};part=(delta.get('content') or '')+(delta.get('reasoning_content') or '')
    if part:first=first or time.perf_counter();answer.append(part)
 if first is None or usage is None:raise RuntimeError('missing first token or usage')
 print(json.dumps({'arm':arm,'label':label,'prompt_tokens':usage.get('prompt_tokens'),'completion_tokens':usage.get('completion_tokens'),'ttft_s':first-t,'elapsed_s':time.perf_counter()-t,'answer':''.join(answer)}),flush=True)
 return ''.join(answer)
def longmsg(i):return base+[{'role':'user','content':f'Give a short status for review {i}.'}]
req('prime',longmsg(0))
for i in range(1,4):req('edited-'+str(i),longmsg(i))
req('switch-b',[{'role':'system','content':'Be precise.'},{'role':'user','content':source[25000:50000]+' Summarize this.'}])
reply=req('return-a',longmsg(3))
req('append-turn',longmsg(3)+[{'role':'assistant','content':reply},{'role':'user','content':'Continue with one more brief observation.'}])

import base64
png=Path(r'<work>\maya\third_party\llama.cpp\media\llama0-logo.png').read_bytes()
image='data:image/png;base64,'+base64.b64encode(png).decode('ascii')
image_messages=[{'role':'user','content':[{'type':'text','text':'Describe the image briefly.'},{'type':'image_url','image_url':{'url':image}}]}]
req('image',image_messages)
req('after-image',longmsg(3))
