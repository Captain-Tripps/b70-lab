"""Copy the L12 candidate tree (ESIMD grouped GEMM) to tree2, add the IQ2_S ESIMD format (patch_iq2s.py), compile
src/forkxmx against the PR head's headers with GGML_SYCL_SUPPORT_XMX (compile_each_l12.py) and relink generate.exe."""
import hashlib, os, pathlib, subprocess, sys
W = pathlib.Path(r'<work>')
exp = W / r'experiments\claude-glm-l12-20261115'
src, root = exp / 'tree', exp / 'tree2'
pr = exp / r'llama-pr\ggml\src\ggml-sycl'
CAND1 = '7112581dd32857efc52d2504fc6607ce68194dbc368820f391960d436ecbdf5a'
sha = lambda p: hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
if not root.exists():
    if sha(src / 'link' / 'generate.exe') != CAND1:
        raise RuntimeError('source tree is not the ESIMD candidate')
    r = subprocess.run(['robocopy', str(src), str(root), '/E', '/NFL', '/NDL', '/NJH', '/NJS', '/NP'])
    if r.returncode >= 8:
        raise RuntimeError('robocopy failed %d' % r.returncode)
    os.replace(root / 'link' / 'generate.exe', root / 'link' / 'cand1-copy.exe')
    # start from the PR's own esimd source, then patch
    (root / 'src' / 'forkxmx' / 'fused-gemm-esimd.cpp').write_bytes((pr / 'fused-gemm-esimd.cpp').read_bytes())
    r = subprocess.run([sys.executable, str(exp / 'patch_iq2s.py'), str(root / 'src' / 'forkxmx'), str(pr), str(exp / 'iq2s_code_table.inc')])
    if r.returncode:
        raise RuntimeError('patch failed')
env = os.environ.copy(); env['ONLY'] = r'src/forkxmx/fused-gemm'
for script, args in [(str(exp / 'compile_each_l12.cmd'), [str(root), '2']), (str(W / 'tools' / 'link_each.cmd'), [str(root), 'generate'])]:
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
print('CANDIDATE2_READY', sha(root / 'link' / 'generate.exe'), flush=True)
