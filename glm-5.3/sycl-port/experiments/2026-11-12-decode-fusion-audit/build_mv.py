"""Compile the one instrumented TU and link inside the isolated copied tree."""
import os
import pathlib
import subprocess
import sys

tree = sys.argv[1] if len(sys.argv) > 1 else 'instrumented-tree'
if tree not in ('instrumented-tree', 'fused-tree'):
    raise RuntimeError('unexpected tree')
root = pathlib.Path(r'D:\maya-sycl\experiments\codex-decode-fusion-audit-20261112') / tree
exe = root / 'link' / 'generate.exe'
reference = root / 'link' / 'generate-before-mv-audit.exe'
if reference.exists() and tree == 'fused-tree':
    reference = root / 'link' / 'generate-before-fused-log.exe'
if not exe.exists() or reference.exists():
    raise RuntimeError('unexpected isolated build state')
exe.rename(reference)
env = os.environ.copy()
env['ONLY'] = r'src/kernels/cuda/glm_fast\.dp\.cpp$'
tools = pathlib.Path(r'D:\maya-sycl\tools')
for script, args in [('compile_each.cmd', [str(root), '1']), ('link_each.cmd', [str(root), 'generate'])]:
    print('START', script, flush=True)
    p = subprocess.run(['cmd.exe', '/d', '/c', str(tools / script), *args], env=env, timeout=1800,
                       creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    if p.returncode:
        raise RuntimeError(f'{script} failed: {p.returncode}')
    if script.startswith('compile'):
        rows = (root / 'compile' / 'summary.tsv').read_text().splitlines()
        if len(rows) != 1 or rows[0].split('\t')[1:3] != ['0', '0']:
            raise RuntimeError('unexpected compile results: ' + str(rows))
    else:
        log = (root / 'link' / 'generate.link.log').read_text(errors='replace').lower()
        if not exe.exists() or 'error:' in log or 'fatal error' in log:
            raise RuntimeError('link failed')
    print('DONE', script, flush=True)
