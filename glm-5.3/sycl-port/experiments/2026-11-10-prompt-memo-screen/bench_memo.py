import os,sys,time,json,statistics,copy
from pathlib import Path
root=Path(r'<work>\experiments\codex-promptmemo-20261110\overlay');sys.path.insert(0,str(root));sys.path.insert(0,str(root/'tools'))
from strata_tokenizer import Tokenizer
from serve.server import Service,MockEngine
from serve.frontend import ChatTemplate
pack=r'<work>\glm-m\pack\tokenizer';template=ChatTemplate(pack+r'\chat_template.jinja')
text=Path(r'<work>\long_body.txt').read_text(encoding='utf8')
for label,chars in [('8k',25000),('32k',104000),('115k',390000)]:
 services=[]
 for mode in ('0','1'):
  tok=Tokenizer.from_dir(pack); services.append(Service(MockEngine(tok,'ok'),tok,template))
 def render(svc,mode,msg):
  os.environ['MAYA_PROMPT_MEMO']=mode;t=time.perf_counter(); ids=svc.render_ids(msg,None,{'enable_thinking':False});return ids,time.perf_counter()-t
 history=[{'role':'system','content':'Be precise.'},{'role':'user','content':text[:chars]}]
 seed0,_=render(services[0],'0',history);seed1,_=render(services[1],'1',history)
 if seed0!=seed1:raise SystemExit('seed mismatch')
 out=[]
 for i in range(3):
  history=history+[{'role':'assistant','content':f'Finished step {i}.'},{'role':'user','content':f'Continue review, step {i+1}.'}]
  pair={}
  order=[0,1] if i%2==0 else [1,0]
  for k in order:
   ids,elapsed=render(services[k],str(k),history);pair[k]=(ids,elapsed)
  if pair[0][0]!=pair[1][0]:raise SystemExit('follow-up mismatch')
  out.append({'iteration':i+1,'tokens':len(pair[0][0]),'off_s':pair[0][1],'on_s':pair[1][1]})
 edited=copy.deepcopy(history);edited[1]['content']=edited[1]['content'][:chars//2]+'\nAn edited earlier section.\n'+edited[1]['content'][chars//2:]
 ai,at=render(services[0],'0',edited); bi,bt=render(services[1],'1',edited)
 if ai!=bi:raise SystemExit('edited mismatch')
 print(json.dumps({'case':label,'seed_tokens':len(seed0),'runs':out,'edit':{'tokens':len(ai),'off_s':at,'on_s':bt},'exact':True}),flush=True)
