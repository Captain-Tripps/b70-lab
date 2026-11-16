"""Copy the live engine tree (q6al), put llama.cpp#31428's grouped GEMM (fused-gemm.cpp + fused-gemm-esimd.cpp, PR head
eec5c09) in src/forkxmx, adapt the shim, compile src/forkxmx against the PR head's headers (JIT) and relink generate.exe.
GGML_SYCL_MMID_ESIMD=0 at run time takes the PR's joint_matrix path instead of ESIMD (same binary)."""
import hashlib, os, pathlib, re, shutil, subprocess, sys

W = pathlib.Path(r'<work>')
src = W / r'experiments\claude-glm-q6al-20261114\tree'
exp = W / r'experiments\claude-glm-l12-20261115'
root = exp / 'tree'
pr = exp / r'llama-pr\ggml'
LIVE = '2c21539a8f57558cabdedb155140ff1e856a6ab4594ffbc15608b934b910b25a'
sha = lambda p: hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()

if not root.exists():
    if sha(src / 'link' / 'generate.exe') != LIVE:
        raise RuntimeError('source tree is not the live build')
    r = subprocess.run(['robocopy', str(src), str(root), '/E', '/NFL', '/NDL', '/NJH', '/NJS', '/NP'])
    if r.returncode >= 8:
        raise RuntimeError('robocopy failed %d' % r.returncode)
    os.replace(root / 'link' / 'generate.exe', root / 'link' / 'live-copy.exe')
fx = root / 'src' / 'forkxmx'
for f in ('fused-gemm.cpp', 'fused-gemm-esimd.cpp'):
    shutil.copyfile(pr / 'src' / 'ggml-sycl' / f, fx / f)
shim = fx / 'maya_fg_shim.cpp'
s = shim.read_text(encoding='utf-8')
s = s.replace('ggml_sycl_gg_tile', 'ggml_sycl_grouped_gemm_tile')
# the precision argument is now the src1 request (ggml_prec); GGML_PREC_UNDEFINED (0, the old GGML_PREC_DEFAULT) asks for none
s = s.replace('x, GGML_PREC_DEFAULT, dst', 'x, GGML_PREC_UNDEFINED, dst')
if 'g_ggml_sycl_mmid_sched' not in s:
    s = s.replace('int g_ggml_sycl_dynamic_required_precision',
                  'int g_ggml_sycl_mmid_sched = GGML_SYCL_MMID_SCHED_DEVICE;   // read only by the device-scheduled entry\n'
                  'int g_ggml_sycl_dynamic_required_precision')
if 'int ggml_sycl_get_env(' not in s:   # ggml-sycl.cpp's env reader; fused-gemm-esimd.cpp reads GGML_SYCL_MMID_ESIMD through it
    s = s.replace('extern "C" int maya_fg_type_ok(int type) {',
                  'int ggml_sycl_get_env(const char* name, int default_val) { return env_int(name, default_val); }\n\n'
                  'extern "C" int maya_fg_type_ok(int type) {')
shim.write_text(s, encoding='utf-8', newline='\n')

ce = (W / 'tools' / 'compile_each.py').read_text(encoding='utf-8')
ce = re.sub(r'fork = pathlib\.Path\(r"[^"]*"\)', lambda m: 'fork = pathlib.Path(r"%s")' % pr, ce)
# the PR's CMake defines GGML_SYCL_SUPPORT_XMX; without it fused-gemm-esimd.cpp compiles but never takes the ESIMD path
ce = ce.replace('"-DGGML_SYCL_F16",', '"-DGGML_SYCL_F16", "-DGGML_SYCL_SUPPORT_XMX",', 1)
if 'GGML_SYCL_SUPPORT_XMX' not in ce:
    raise RuntimeError('could not add GGML_SYCL_SUPPORT_XMX')
(exp / 'compile_each_l12.py').write_text(ce, encoding='utf-8')
cmd = (W / 'tools' / 'compile_each.cmd').read_text(encoding='utf-8').replace(r'<work>\tools\compile_each.py', str(exp / 'compile_each_l12.py'))
(exp / 'compile_each_l12.cmd').write_text(cmd, encoding='utf-8')

env = os.environ.copy(); env['ONLY'] = r'src/forkxmx/'
for script, args in [(str(exp / 'compile_each_l12.cmd'), [str(root), '3']), (str(W / 'tools' / 'link_each.cmd'), [str(root), 'generate'])]:
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
print('CANDIDATE_READY', sha(root / 'link' / 'generate.exe'), flush=True)
