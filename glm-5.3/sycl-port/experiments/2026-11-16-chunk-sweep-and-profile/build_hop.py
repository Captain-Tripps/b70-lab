"""L16 hop probe: copy the live tree (L14, tile-m32-n64) to hop-probe, patch the prompt hand-off copies (patch_hop.py),
compile src/core/glm_prefill.dp.cpp with the engine's usual flags and relink generate.exe."""
import hashlib, os, pathlib, subprocess, sys
W = pathlib.Path(r'<work>')
exp = W / r'experiments\claude-glm-l12-20261115'
src, root = exp / 'tile-m32-n64', exp / 'hop-probe'
LIVE = 'f27bcbf34cb897cf2d0e91d19716ec831b526ae7f67292d625e95f31d5d2e976'
sha = lambda p: hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
if not root.exists():
    if sha(src / 'link' / 'generate.exe') != LIVE:
        raise RuntimeError('source tree is not the live build')
    r = subprocess.run(['robocopy', str(src), str(root), '/E', '/NFL', '/NDL', '/NJH', '/NJS', '/NP'])
    if r.returncode >= 8:
        raise RuntimeError('robocopy failed %d' % r.returncode)
    os.replace(root / 'link' / 'generate.exe', root / 'link' / 'live-copy.exe')
    r = subprocess.run([sys.executable, str(exp / 'patch_hop.py'), str(root)])
    if r.returncode:
        raise RuntimeError('patch failed')
env = os.environ.copy(); env['ONLY'] = r'src/core/glm_prefill'
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
print('HOP_READY', sha(root / 'link' / 'generate.exe'), flush=True)
