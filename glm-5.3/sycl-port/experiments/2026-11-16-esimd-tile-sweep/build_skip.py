"""L15 tail packing: copy a built tile-sweep tree (tile-m<MR>-n<BN>) to ...s and make the ESIMD grouped kernel skip
the packed-B loads and dpas of every NW-wide column block at or past the tile's last real column (ncols). Those
accumulators are never stored, so the output is the same bits; a 43-row expert in a 64-wide tile does 3 of 4
blocks. Recompiles fused-gemm-esimd.cpp only and relinks.

usage: python build_skip.py tile-m32-n64 [more trees]"""
import hashlib, os, pathlib, subprocess, sys
W = pathlib.Path(r'<work>')
exp = W / r'experiments\claude-glm-l12-20261115'
sha = lambda p: hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()

OLD1 = '                    b[nt] = load_2d<uint32_t, NW, 16>(bp, bw - 1, K / 2 - 1, bw - 1, b0 + nt * NW, kb * 16);\n'
NEW1 = ('                    if (nt * NW < ncols) {   // L15: no loads for empty column blocks\n'
        '    ' + OLD1 + '                    }\n')
OLD2 = ('                        simd<uint32_t, 8 * NW> bh32 = b[nt].template select<8 * NW, 1>(h * 8 * NW);\n'
        '                        simd<T, 16 * NW>       bh   = bh32.template bit_cast_view<T>();\n'
        '                        acc[g][nt] = xmx::dpas<8, RC, float, float>(acc[g][nt], bh, at);\n')
NEW2 = ('                        if (nt * NW < ncols) {   // L15: no dpas for empty column blocks\n'
        + ''.join('    ' + l + '\n' for l in OLD2.splitlines()) + '                        }\n')

for name in sys.argv[1:]:
    src, root = exp / name, exp / (name + 's')
    print('VARIANT', root.name, flush=True)
    if not root.exists():
        if not (src / 'link' / 'generate.exe').exists():
            raise RuntimeError('source variant not built')
        r = subprocess.run(['robocopy', str(src), str(root), '/E', '/NFL', '/NDL', '/NJH', '/NJS', '/NP'])
        if r.returncode >= 8:
            raise RuntimeError('robocopy failed %d' % r.returncode)
        os.replace(root / 'link' / 'generate.exe', root / 'link' / 'unskipped.exe')
        p = root / 'src' / 'forkxmx' / 'fused-gemm-esimd.cpp'
        s = p.read_text(encoding='utf-8')
        assert s.count(OLD1) == 1 and s.count(OLD2) == 1
        p.write_text(s.replace(OLD1, NEW1).replace(OLD2, NEW2), encoding='utf-8', newline='\n')
    env = os.environ.copy(); env['ONLY'] = r'src/forkxmx/fused-gemm-esimd'
    ok = True
    for script, a in [(str(exp / 'compile_each_l12.cmd'), [str(root), '1']), (str(W / 'tools' / 'link_each.cmd'), [str(root), 'generate'])]:
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
print('SKIP_BUILDS_DONE', flush=True)
