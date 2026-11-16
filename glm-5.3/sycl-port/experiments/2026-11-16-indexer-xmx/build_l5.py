"""L5: copy the live tree (L12 step 2, tree2) to tree4, add the XMX indexer score behind STRATA_GLM_DSA_XMX
(patch_dsa.py), compile src/kernels/cuda/glm_batch.dp.cpp with the engine's usual flags and relink generate.exe."""
import hashlib, os, pathlib, subprocess, sys
W = pathlib.Path(r'<work>')
exp = W / r'experiments\claude-glm-l12-20261115'
src, root = exp / 'tree2', exp / 'tree4'
LIVE = '1a6289326f57f01bc1dd3d8bb378a5b4b0605e3628994409b65de8e5410a33ee'
sha = lambda p: hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
if not root.exists():
    if sha(src / 'link' / 'generate.exe') != LIVE:
        raise RuntimeError('source tree is not the live build')
    r = subprocess.run(['robocopy', str(src), str(root), '/E', '/NFL', '/NDL', '/NJH', '/NJS', '/NP'])
    if r.returncode >= 8:
        raise RuntimeError('robocopy failed %d' % r.returncode)
    os.replace(root / 'link' / 'generate.exe', root / 'link' / 'live-copy.exe')
    r = subprocess.run([sys.executable, str(exp / 'patch_dsa.py'), str(root)])
    if r.returncode:
        raise RuntimeError('patch failed')
env = os.environ.copy(); env['ONLY'] = r'src/kernels/cuda/glm_batch'
for script, args in [(str(W / 'tools' / 'compile_each.cmd'), [str(root), '1']), (str(W / 'tools' / 'link_each.cmd'), [str(root), 'generate'])]:
    print('START', script, flush=True)
    r = subprocess.run(['cmd.exe', '/d', '/c', script, *args], env=env, creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS, timeout=5400)
    if r.returncode:
        raise RuntimeError(script + ' failed ' + str(r.returncode))
    if 'compile' in script:
        rows = (root / 'compile' / 'summary.tsv').read_text().splitlines()
        print('\n'.join(rows), flush=True)
        if any(row.split('\t')[2] != '0' for row in rows):
            raise RuntimeError('compile errors')
    else:
        log = (root / 'link' / 'generate.link.log').read_text(errors='replace')
        if not (root / 'link' / 'generate.exe').exists() or 'error' in log.lower():
            print(log[-3000:]); raise RuntimeError('link failed')
    print('DONE', script, flush=True)
print('L5_READY', sha(root / 'link' / 'generate.exe'), flush=True)
