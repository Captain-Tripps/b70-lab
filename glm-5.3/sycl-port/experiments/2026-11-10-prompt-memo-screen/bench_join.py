import time,json,sys
from pathlib import Path
p=Path(r'<work>\experiments\codex-promptmemo-20261110');sys.path.insert(0,str(p))
from join_ids_memo import join_ids_memo
ids=[int(x) for x in Path(r'<work>\long32k.txt').read_text().split(',')]
for n in (8192,32768,115100):
 base=(ids*(n//len(ids)+1))[:n]; memo={};assert join_ids_memo(memo,base)==','.join(str(int(t)) for t in base)
 runs=[]
 for i in range(5):
  data=base+list(range(100+i));t=time.perf_counter();a=','.join(str(int(t)) for t in data);off=time.perf_counter()-t
  t=time.perf_counter();b=join_ids_memo(memo,data);on=time.perf_counter()-t
  if a!=b:raise AssertionError('mismatch')
  runs.append({'off_s':off,'on_s':on})
 print(json.dumps({'tokens':n,'runs':runs,'exact':True}),flush=True)
