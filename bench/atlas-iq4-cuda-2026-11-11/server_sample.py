import hashlib,json,sys,time,urllib.request
from pathlib import Path
arm=sys.argv[1]; port=int(sys.argv[2]); run=int(sys.argv[3]); out=Path(sys.argv[4])
def get(path):
    with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}',timeout=5) as r:return json.load(r)
s=get('/slots')[0]
if s.get('is_processing'):sys.exit('server is busy')
prompt=('A systems engineer studies an inference service. The test measures GPU memory, cache reuse, scheduling, and numerical accuracy.\n'*32 + '\nWrite a detailed numbered technical analysis of performance bottlenecks and practical experiments.\n')
data=json.dumps({'prompt':prompt,'n_predict':160,'temperature':0,'seed':42,'cache_prompt':False,'ignore_eos':True,'stream':False}).encode()
req=urllib.request.Request(f'http://127.0.0.1:{port}/completion',data=data,headers={'Content-Type':'application/json'})
t=time.monotonic()
with urllib.request.urlopen(req,timeout=300) as r: result=json.load(r)
elapsed=time.monotonic()-t
now=get('/slots')[0]
if now.get('is_processing'):sys.exit('server became busy')
row={'arm':arm,'run':run,'wall_s':elapsed,'tokens_predicted':result.get('tokens_predicted'),'tokens_evaluated':result.get('tokens_evaluated'),'timings':result.get('timings'),'output_sha256':hashlib.sha256(result.get('content','').encode()).hexdigest(),'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'slot_task_before':s.get('id_task'),'slot_task_after':now.get('id_task')}
with out.open('a') as f:f.write(json.dumps(row)+'\n')
print(json.dumps(row),flush=True)
