"""Copy the live engine tree (q6al), apply patch_dvocab.py, rebuild glm_mtp.dp.cpp and relink generate.exe."""
import hashlib, os, pathlib, subprocess, sys

src = pathlib.Path(r'<work>\experiments\q6al\tree')
exp = pathlib.Path(r'<work>\experiments\dvocab')
root = exp / 'tree'
LIVE = '2c21539a8f57558cabdedb155140ff1e856a6ab4594ffbc15608b934b910b25a'


def sha(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


if root.exists():
    raise RuntimeError('tree exists')
if sha(src / 'link' / 'generate.exe') != LIVE:
    raise RuntimeError('source tree is not the live build')
r = subprocess.run(['robocopy', str(src), str(root), '/E', '/NFL', '/NDL', '/NJH', '/NJS', '/NP'])
if r.returncode >= 8:
    raise RuntimeError('robocopy failed %d' % r.returncode)
exe = root / 'link' / 'generate.exe'
os.replace(exe, root / 'link' / 'live-copy.exe')
r = subprocess.run([sys.executable, str(exp / 'patch_dvocab.py'), str(root)])
if r.returncode:
    raise RuntimeError('patch failed')
env = os.environ.copy(); env['ONLY'] = r'src/core/glm_mtp\.dp\.cpp$'
for script, args in [('compile_each.cmd', [str(root), '1']), ('link_each.cmd', [str(root), 'generate'])]:
    print('START', script, flush=True)
    r = subprocess.run(['cmd.exe', '/d', '/c', str(pathlib.Path(r'<work>\tools') / script), *args], env=env,
                       creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS, timeout=3600)
    if r.returncode:
        raise RuntimeError(script + ' failed ' + str(r.returncode))
    if script.startswith('compile'):
        rows = (root / 'compile' / 'summary.tsv').read_text().splitlines()
        if len(rows) != 1 or rows[0].split('\t')[1:3] != ['0', '0']:
            raise RuntimeError('compile errors: ' + str(rows))
    if script.startswith('link'):
        log = (root / 'link' / 'generate.link.log').read_text(errors='replace')
        if not exe.exists() or 'error:' in log.lower() or 'fatal error' in log.lower():
            raise RuntimeError('link failed')
    print('DONE', script, flush=True)
print('CANDIDATE_READY', exe, sha(exe), flush=True)
