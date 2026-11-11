import os,sys,copy,unittest,random
from pathlib import Path
root=Path(r'<work>\experiments\codex-promptmemo-20261110\overlay');sys.path.insert(0,str(root));sys.path.insert(0,str(root/'tools'))
from strata_tokenizer import Tokenizer
from serve.server import Service,MockEngine
from serve.frontend import ChatTemplate,openai_to_messages
tok=Tokenizer.from_dir(r'<work>\glm-m\pack\tokenizer')
template=ChatTemplate(r'<work>\glm-m\pack\tokenizer\chat_template.jinja')
svc=Service(MockEngine(tok,'ok'),tok,template)
class Check(unittest.TestCase):
 def ids(self,req,mode,suffix=''):
  os.environ['MAYA_PROMPT_MEMO']=mode
  m,t,kw=openai_to_messages(copy.deepcopy(req));return svc.render_ids(m,t,kw,suffix)
 def same(self,req):
  a=self.ids(req,'0');b=self.ids(req,'verify');self.assertEqual(a,b)
 def test_histories_and_fuzz(self):
  tool={'type':'function','function':{'name':'read_file','description':'read file','parameters':{'type':'object','properties':{'path':{'type':'string'}}}}}
  history=[{'role':'system','content':'You are a careful assistant.'},{'role':'user','content':'Read <|user|> literally and summarize.'}]
  cases=[{'messages':history,'tools':[tool]}]
  cases.append({'messages':history+[{'role':'assistant','content':'<think>Checking.</think> Done.'},{'role':'user','content':'What changed?'}],'tools':[tool]})
  cases.append({'messages':history+[{'role':'assistant','content':None,'tool_calls':[{'id':'call_123','type':'function','function':{'name':'read_file','arguments':'{"path":"/tmp/a"}'}}]},{'role':'tool','tool_call_id':'call_123','content':'file content'},{'role':'user','content':'Summarize it.'}],'tools':[tool]})
  cases.extend([{'messages':[{'role':'system','content':'New rules'},*history[1:]],'tools':[tool]},{'messages':history[1:]},{'messages':[{'role':'user','content':'Unrelated conversation'}]},{'messages':[{'role':'user','content':'unicode 日本語 café 🚀 <|assistant|> </think>'}]}])
  for req in cases:self.same(req)
  rng=random.Random(813)
  for i in range(50):
   content=''.join(rng.choice(['abc',' ', '<|user|>','</think>','日本語','\n','123']) for _ in range(50))
   self.same({'messages':[{'role':'user','content':content},{'role':'assistant','content':'answer'},{'role':'user','content':str(i)}]})
  self.assertTrue(svc._prompt_memo.usable())
 def test_suffix_fallback(self):
  req={'messages':[{'role':'user','content':'hello <|user|>'}]}
  self.assertEqual(self.ids(req,'0','suffix'),self.ids(req,'1','suffix'))
 def test_image_bypass(self):
  original=svc.template.render
  svc.template.render=lambda *args,**kwargs:'safe text'
  try:
   if getattr(svc,'_prompt_memo',None) is None:self.same({'messages':[{'role':'user','content':'warm'}]})
   old=svc._prompt_memo.encode
   def fail(*args):raise AssertionError('image should bypass memo')
   svc._prompt_memo.encode=fail
   try:svc.render_ids([{'role':'user','content':[{'type':'image','source':'fake'}]}],None,{})
   finally:svc._prompt_memo.encode=old
  finally:svc.template.render=original
if __name__=='__main__':unittest.main(verbosity=2)
