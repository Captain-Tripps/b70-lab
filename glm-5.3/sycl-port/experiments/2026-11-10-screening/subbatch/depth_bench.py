import argparse, json, time, urllib.request
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument('--url',default='http://127.0.0.1:9073')
p.add_argument('--model',default='glm-5.3-flash-maya-sycl')
p.add_argument('--doc',required=True)
p.add_argument('--depth',type=int,default=8000)
p.add_argument('--repeat',type=int,default=3)
p.add_argument('--output',required=True)
p.add_argument('--tokens',type=int,default=64)
p.add_argument('--tag',required=True)
p.add_argument("--offset",type=int,default=0)
a=p.parse_args()
src=Path(a.doc).read_text(encoding='utf-8')
length=a.depth*4
filler=(src*((length//len(src))+1))[:length]
with open(a.output,'w',encoding='utf-8') as out:
    for i in range(a.repeat):
        prompt=f'Fresh document run {i+1+a.offset}. Summarize the following file in a single sentence.\n\n'+filler
        body={'model':a.model,'messages':[{'role':'user','content':prompt}],'max_tokens':a.tokens,'temperature':0,'seed':1,'stream':True,'stream_options':{'include_usage':True},'chat_template_kwargs':{'enable_thinking':False}}
        req=urllib.request.Request(a.url+'/v1/chat/completions',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
        t0=time.perf_counter(); first=None; last=None; usage=None; chunks=0; content=[]
        with urllib.request.urlopen(req,timeout=3600) as r:
            for raw in r:
                line=raw.decode('utf-8','replace').strip()
                if not line.startswith('data:'): continue
                data=line[5:].strip()
                if data=='[DONE]': break
                ev=json.loads(data); usage=ev.get('usage') or usage
                for choice in ev.get('choices',[]):
                    d=choice.get('delta') or {}; part=(d.get('content') or '')+(d.get('reasoning_content') or '')
                    if part:
                        now=time.perf_counter(); first=first or now; last=now; chunks+=1; content.append(part)
        if not first or not usage: raise RuntimeError('missing first token or usage')
        ntok=usage.get('completion_tokens',chunks)
        record={'tag':a.tag,'run':i+1,'requested_depth_approx':a.depth,'prompt_tokens':usage.get('prompt_tokens'),'output_tokens':ntok,'ttft_s':first-t0,'elapsed_s':time.perf_counter()-t0,'decode_tps':(ntok-1)/(last-first) if last and last>first else None,'answer':''.join(content)}
        out.write(json.dumps(record,ensure_ascii=False)+'\n'); out.flush(); print(json.dumps(record,ensure_ascii=False),flush=True)
