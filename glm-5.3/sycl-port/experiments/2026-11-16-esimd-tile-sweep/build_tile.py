"""L14 tile sweep: copy the live tree (L5, tree4) to tile-m<MR>-n<BN>, set the ESIMD grouped kernel's rows per thread
(GROUPED_GEMM_MR) and the grouped schedule's tile width (GGML_SYCL_FG_BN, which the joint_matrix shapes and the ESIMD
kernel share), compile src/forkxmx against the PR head's headers and relink generate.exe.

usage: python build_tile.py MR BN [MR BN ...]"""
import hashlib, os, pathlib, subprocess, sys
W = pathlib.Path(r'<work>')
exp = W / r'experiments\claude-glm-l12-20261115'
src = exp / 'tree4'
LIVE = 'f72801f6fefd39b68802ac63c667f56f577b14480434793c0498e72508491ca4'
hdr = exp / r'llama-pr\ggml\src\ggml-sycl\fused-gemm.hpp'
sha = lambda p: hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()

# the shared header takes its tile width from MAYA_FG_BN, 32 when unset (every earlier build)
h = hdr.read_text(encoding='utf-8')
if 'MAYA_FG_BN' not in h:
    old = 'static constexpr int GGML_SYCL_FG_BN = 32;'
    assert h.count(old) == 1
    h = h.replace(old, '#ifndef MAYA_FG_BN\n#define MAYA_FG_BN 32\n#endif\nstatic constexpr int GGML_SYCL_FG_BN = MAYA_FG_BN;')
    hdr.write_text(h, encoding='utf-8', newline='\n')


def patch(root, mr, bn):
    fx = root / 'src' / 'forkxmx'
    for name in ('fused-gemm.cpp', 'fused-gemm-esimd.cpp', 'maya_fg_shim.cpp'):
        p = fx / name
        s = p.read_text(encoding='utf-8')
        s = '#define MAYA_FG_BN %d   // L14 tile sweep\n' % bn + s
        if name == 'fused-gemm.cpp':
            old = 'static constexpr int BN      = TN > 32 ? TN : 32;'
            assert s.count(old) == 1
            s = s.replace(old, 'static constexpr int BN      = TN > GGML_SYCL_FG_BN ? TN : GGML_SYCL_FG_BN;')
        if name == 'fused-gemm-esimd.cpp':
            old = 'static constexpr int GROUPED_GEMM_MR               = 32;'
            assert s.count(old) == 1
            s = s.replace(old, 'static constexpr int GROUPED_GEMM_MR               = %d;' % mr)
        p.write_text(s, encoding='utf-8', newline='\n')


args = [int(a) for a in sys.argv[1:]]
for mr, bn in zip(args[0::2], args[1::2]):
    root = exp / ('tile-m%d-n%d' % (mr, bn))
    print('VARIANT', root.name, flush=True)
    if not root.exists():
        if sha(src / 'link' / 'generate.exe') != LIVE:
            raise RuntimeError('source tree is not the live build')
        r = subprocess.run(['robocopy', str(src), str(root), '/E', '/NFL', '/NDL', '/NJH', '/NJS', '/NP'])
        if r.returncode >= 8:
            raise RuntimeError('robocopy failed %d' % r.returncode)
        os.replace(root / 'link' / 'generate.exe', root / 'link' / 'live-copy.exe')
        patch(root, mr, bn)
    env = os.environ.copy(); env['ONLY'] = r'src/forkxmx/'
    ok = True
    for script, a in [(str(exp / 'compile_each_l12.cmd'), [str(root), '3']), (str(W / 'tools' / 'link_each.cmd'), [str(root), 'generate'])]:
        r = subprocess.run(['cmd.exe', '/d', '/c', script, *a], env=env, creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS, timeout=5400,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if 'compile' in script:
            rows = (root / 'compile' / 'summary.tsv').read_text().splitlines()
            print('\n'.join(rows), flush=True)
            if r.returncode or any(row.split('\t')[2] != '0' for row in rows):
                print('COMPILE_FAILED', root.name, flush=True); ok = False; break
        else:
            log = (root / 'link' / 'generate.link.log').read_text(errors='replace')
            if r.returncode or not (root / 'link' / 'generate.exe').exists() or 'error' in log.lower():
                print(log[-1500:]); print('LINK_FAILED', root.name, flush=True); ok = False
    if ok:
        print('READY', root.name, sha(root / 'link' / 'generate.exe'), flush=True)
print('TILE_BUILDS_DONE', flush=True)
