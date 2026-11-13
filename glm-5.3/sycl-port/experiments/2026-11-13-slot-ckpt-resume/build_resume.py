import hashlib, os, pathlib, subprocess, sys

src = pathlib.Path(r'D:\maya-sycl\experiments\codex-glm-ckpt-carry-20261113\tree')
exp = pathlib.Path(r'D:\maya-sycl\experiments\codex-glm-ckpt-resume-20261113')
root = exp / 'tree'
CARRY = '76295f72901b9d21dca17bee226c4456a9cb7f4c9adf4f1acc4f70bc904d5b8d'

def sha(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()

if root.exists():
    raise RuntimeError('tree exists')
if sha(src / 'link' / 'generate.exe') != CARRY:
    raise RuntimeError('source tree is not the carry build')
r = subprocess.run(['robocopy', str(src), str(root), '/E', '/NFL', '/NDL', '/NJH', '/NJS', '/NP'])
if r.returncode >= 8:
    raise RuntimeError('robocopy failed %d' % r.returncode)
exe = root / 'link' / 'generate.exe'
exe.rename(root / 'link' / 'carry-copy.exe')
r = subprocess.run([sys.executable, str(exp / 'patch_ckpt_resume.py'), str(root)])
if r.returncode:
    raise RuntimeError('patch failed')
env = os.environ.copy(); env['ONLY'] = r'src/program/generate\.cpp$'
for script, args in [('compile_each.cmd', [str(root), '1']), ('link_each.cmd', [str(root), 'generate'])]:
    print('START', script, flush=True)
    r = subprocess.run(['cmd.exe', '/d', '/c', str(pathlib.Path(r'D:\maya-sycl\tools') / script), *args], env=env,
                       creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS, timeout=900)
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
