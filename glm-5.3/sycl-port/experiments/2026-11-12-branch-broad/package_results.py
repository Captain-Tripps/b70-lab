import json, pathlib, re, shutil, sys

work=pathlib.Path(sys.argv[1]);out=work/'experiments'/'codex-slot-branch-broad-20261112'/'artifact-package'
if out.exists():raise FileExistsError(f'refusing to replace existing artifact directory: {out}')
tests={'broad12':work/'experiments'/'codex-slot-branch-broad-20261112','cap1gb':work/'experiments'/'codex-slot-branch-cap1gb-20261112','fairness':work/'experiments'/'codex-slot-branch-fairness-20261112'}
for test,root in tests.items():
 for arm in ('off','on'):
  dest=out/test/arm;dest.mkdir(parents=True,exist_ok=True)
  for name in ('requests.jsonl','memory.jsonl','slots-samples.jsonl','server.log','engine.log'):
   p=root/arm/name
   if not p.exists():continue
   if p.suffix=='.log':
    content=p.read_text(encoding='utf8',errors='replace').replace('D:\\maya-sycl','<work>')
    (dest/name).write_text(content,encoding='utf8')
   else:shutil.copy2(p,dest/name)
shutil.copy2(tests['broad12']/'summary.json',out/'summary.json')
print(out)
