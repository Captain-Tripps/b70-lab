import os,sys,unittest,concurrent.futures
from pathlib import Path
root=Path(r'<work>\experiments\codex-promptmemo-20261110\overlay');sys.path.insert(0,str(root));sys.path.insert(0,str(root/'tools'))
from serve.server import memo_ids_text
class Engine: pass
class Check(unittest.TestCase):
 def test_edits_and_histories(self):
  os.environ['MAYA_PROMPT_MEMO']='verify'; engine=Engine();base=list(range(12000))
  cases=[[],base,base+[1,2],base[:8000]+[91,92],base[:1024],list(reversed(base)),base+[9],tuple(base)]
  for ids in cases:self.assertEqual(memo_ids_text(engine,ids),','.join(str(int(t)) for t in ids))
 def test_concurrent(self):
  os.environ['MAYA_PROMPT_MEMO']='verify';engine=Engine();cases=[list(range(5000))+[i] for i in range(24)]
  with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:out=list(ex.map(lambda ids:memo_ids_text(engine,ids),cases))
  self.assertEqual(out,[','.join(str(int(t)) for t in ids) for ids in cases])
if __name__=='__main__':unittest.main(verbosity=2)
