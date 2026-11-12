import hashlib, json, pathlib, re, sys

work=pathlib.Path(sys.argv[1])
base=work/'experiments'/'codex-slot-branch-broad-20261112'
def read_rows(path):return [json.loads(line) for line in path.read_text(encoding='utf8').splitlines() if line.strip()]
def arm_summary(folder):
 rows=read_rows(folder/'requests.jsonl');mem=read_rows(folder/'memory.jsonl');logs=(folder/'engine.log').read_text(encoding='utf8',errors='replace')
 saved=[]
 rx=re.compile(r'saved a (\d+)-token conversation \(([\d.]+) GB in RAM.*?; (\d+) kept, ([\d.]+) GB(.*)$')
 for line in logs.splitlines():
  m=rx.search(line)
  if m:saved.append({'tokens':int(m[1]),'entry_gb':float(m[2]),'kept':int(m[3]),'retained_gb':float(m[4]),'eviction':m[5].strip()})
 procs=[x['generate_process'] for x in mem if x.get('generate_process')]
 return {'request_count':len(rows),'requests':rows,'min_host_available_gib':round(min(x['free_bytes'] for x in mem)/1024**3,2),'max_generate_working_set_gib':round(max(x['WorkingSetSize'] for x in procs)/1024**3,2) if procs else None,'max_generate_private_bytes_gib':round(max(x['PrivatePageCount'] for x in procs)/1024**3,2) if procs else None,'generate_process_samples':len(procs),'slot_save_rows':saved,'max_kept_slots':max((x['kept'] for x in saved),default=0),'max_logged_retained_gb':max((x['retained_gb'] for x in saved),default=0),'count_at_8_rows':sum(x['kept']==8 for x in saved),'byte_cap_lru_evictions':sum('least recently used dropped to stay under the RAM cap' in x['eviction'] for x in saved)}

out={}
for name,folder in [('broad12_off',base/'off'),('broad12_on',base/'on'),('cap1_off',work/'experiments'/'codex-slot-branch-cap1gb-20261112'/'off'),('cap1_on',work/'experiments'/'codex-slot-branch-cap1gb-20261112'/'on'),('fair_off',work/'experiments'/'codex-slot-branch-fairness-20261112'/'off'),('fair_on',work/'experiments'/'codex-slot-branch-fairness-20261112'/'on')]:
 out[name]=arm_summary(folder)
for pair in [('broad12_off','broad12_on'),('cap1_off','cap1_on'),('fair_off','fair_on')]:
 a,b=(out[x]['requests'] for x in pair)
 out[pair[0]+'__vs__'+pair[1]]={'same_labels':[x['label'] for x in a]==[x['label'] for x in b],'same_output_hashes':len(a)==len(b) and all(x['output_sha256']==y['output_sha256'] for x,y in zip(a,b)),'request_count':len(a)}
for key in ('broad12_off','broad12_on','cap1_off','cap1_on','fair_off','fair_on'):
 rows=out[key]['requests'];out[key]['ttft_s']={x['label']:round(x['ttft_s'],3) if x['ttft_s'] is not None else None for x in rows if x['label'] in ('B-prime','B-revisit','B-repeat','B-after-images','image-llama0','image-llama1','image-llama0-repeat')}
media=work/'maya'/'third_party'/'llama.cpp'/'media'
out['image_input_sha256']={n:hashlib.sha256((media/n).read_bytes()).hexdigest() for n in ('llama0-logo.png','llama1-logo.png')}
outpath=base/'summary.json';outpath.write_text(json.dumps(out,indent=2),encoding='utf8');print(outpath);print(json.dumps({k:v for k,v in out.items() if '__vs__' in k or k=='image_input_sha256'},indent=2))
