"""GLM r3 (STRATA_GLM_MV_AL16): copies the live idlefix tree to claude-glm-r1-20261119\\al16, patches glm_fast.dp.cpp,
compiles only that file, relinks generate.exe. The live tree and exe are not touched."""
import hashlib, os, pathlib, subprocess, sys
W = pathlib.Path(r'D:\maya-sycl')
l12 = W / r'experiments\claude-glm-l12-20261115'
src = l12 / 'idlefix'
exp = W / r'experiments\claude-glm-r1-20261119'
root = exp / 'al16'
LIVE = '7559cf05c285a18463c278afa769b660'
md5 = lambda p: hashlib.md5(pathlib.Path(p).read_bytes()).hexdigest()
if md5(src / 'link' / 'generate.exe') != LIVE:
    raise RuntimeError('source tree is not the live build')
exp.mkdir(parents=True, exist_ok=True)
if not root.exists():
    r = subprocess.run(['robocopy', str(src), str(root), '/E', '/NFL', '/NDL', '/NJH', '/NJS', '/NP'])
    if r.returncode >= 8:
        raise RuntimeError('robocopy failed %d' % r.returncode)
    os.replace(root / 'link' / 'generate.exe', root / 'link' / 'live-copy.exe')
f = root / 'src' / 'kernels' / 'cuda' / 'glm_fast.dp.cpp'
if 'mv_q6_al16_kernel' not in f.read_text(encoding='utf-8'):
    subprocess.run([sys.executable, str(exp / 'glm_r3_al16.py'), str(f)], check=True)
print('PATCHED', flush=True)
env = os.environ.copy(); env['ONLY'] = 'src/kernels/cuda/glm_fast.dp.cpp'
ok = True
for script, a in [(str(l12 / 'compile_each_l12.cmd'), [str(root), '3']), (str(W / 'tools' / 'link_each.cmd'), [str(root), 'generate'])]:
    r = subprocess.run(['cmd.exe', '/d', '/c', script, *a], env=env, creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS,
                       timeout=5400, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if 'compile' in script:
        rows = (root / 'compile' / 'summary.tsv').read_text().splitlines()
        print('\n'.join(rows[-5:]), flush=True)
        if r.returncode or any(row.split('\t')[2] != '0' for row in rows):
            print('COMPILE_FAILED', flush=True); ok = False; break
    else:
        log = (root / 'link' / 'generate.link.log').read_text(errors='replace')
        if r.returncode or not (root / 'link' / 'generate.exe').exists() or 'error' in log.lower():
            print(log[-1500:]); print('LINK_FAILED', flush=True); ok = False
if ok:
    print('READY', md5(root / 'link' / 'generate.exe'), flush=True)
print('DONE', flush=True)
