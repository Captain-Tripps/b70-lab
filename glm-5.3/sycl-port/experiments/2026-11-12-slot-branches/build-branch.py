import os, pathlib, subprocess, time
root=pathlib.Path(r'<work>\experiments\codex-slot-branch-20261112\tree')
env=os.environ.copy();env['ONLY']=r'src/program/generate\.cpp$'
exe=root/'link'/'generate.exe';old=root/'link'/'baseline-copy.exe'
if old.exists():raise RuntimeError('refusing to overwrite prior baseline')
exe.rename(old)
for script,args in [('compile_each.cmd',[str(root),'1']),('link_each.cmd',[str(root),'generate'])]:
 print('START',script,flush=True)
 r=subprocess.run(['cmd.exe','/d','/c',str(pathlib.Path(r'<work>\tools')/script),*args],env=env,creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS,timeout=600)
 if r.returncode:raise RuntimeError(script+' failed '+str(r.returncode))
 if script.startswith('compile'):
  rows=(root/'compile'/'summary.tsv').read_text().splitlines()
  if len(rows)!=1 or rows[0].split('\t')[1:3]!=['0','0']:raise RuntimeError('compile errors: '+str(rows))
 if script.startswith('link'):
  log=(root/'link'/'generate.link.log').read_text(errors='replace')
  if not exe.exists() or 'error:' in log.lower() or 'fatal error' in log.lower():raise RuntimeError('link failed')
 print('DONE',script,flush=True)
print('VARIANT_READY',exe,flush=True)
