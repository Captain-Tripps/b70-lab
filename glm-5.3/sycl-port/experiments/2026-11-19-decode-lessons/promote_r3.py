# GLM r3 promotion: new runtime dir with the r3 exe, config backup, exe path + STRATA_GLM_MV_AL16=1. Text edits only.
import hashlib, pathlib, shutil, json
W = pathlib.Path('<work>')
src = W / 'experiments/claude-glm-r1-20261119/al16/link/generate.exe'
rt = W / 'rt-glm-al16-20261119'; rt.mkdir(exist_ok=True)
assert hashlib.md5(src.read_bytes()).hexdigest() == '79f714d1b7b5dba09efd3feaaec50ac4'
shutil.copy2(src, rt / 'generate.exe')
assert hashlib.md5((rt / 'generate.exe').read_bytes()).hexdigest() == '79f714d1b7b5dba09efd3feaaec50ac4'
cfg = W / 'configs/glm-maya-sycl-128k.json'
bak = W / 'configs/glm-maya-sycl-128k.json.bak-preal16-20261119'
if bak.exists(): assert bak.read_bytes() == cfg.read_bytes(), 'backup differs'
else: shutil.copy2(cfg, bak)
b = cfg.read_bytes()
S = bytes([92, 92])   # the JSON's escaped backslash, built without a literal (the push tool halves them)
old_exe = b'"<work>' + S + b'rt-glm-esimd-iq2s-dsaxmx-tile64-20261116' + S + b'generate.exe"'
new_exe = b'"<work>' + S + b'rt-glm-al16-20261119' + S + b'generate.exe"'
assert b.count(old_exe) == 1, 'exe line'
b = b.replace(old_exe, new_exe)
old_env = b'"STRATA_GLM_DSA_XMX": "1"'
assert b.count(old_env) == 1, 'env line'
nl = b'\r\n' if b'\r\n' in b else b'\n'
b = b.replace(old_env, old_env + b',' + nl + b'    "STRATA_GLM_MV_AL16": "1"')
cfg.write_bytes(b)
c = json.loads(b.decode('utf-8'))
print('exe', c['exe']); print('AL16', c['env']['STRATA_GLM_MV_AL16'], 'DSA_XMX', c['env']['STRATA_GLM_DSA_XMX'])
