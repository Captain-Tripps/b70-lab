"""Point the GLM engine config at the 64-wide ESIMD tile build (L14); the L5 switch stays on, after a clean soak. Backup kept beside it."""
import hashlib, json, pathlib, shutil, sys
p = pathlib.Path(r'<work>\configs\glm-maya-sycl-128k.json')
bak = p.with_name('glm-maya-sycl-128k.json.bak-pretile64-20261116')
OLD = 'f72801f6fefd39b68802ac63c667f56f577b14480434793c0498e72508491ca4'
SRC = pathlib.Path(r'<work>\experiments\claude-glm-l12-20261115\tile-m32-n64\link\generate.exe')
NEW_DIR = pathlib.Path(r'<work>\rt-glm-esimd-iq2s-dsaxmx-tile64-20261116')
NEW = 'f27bcbf34cb897cf2d0e91d19716ec831b526ae7f67292d625e95f31d5d2e976'
sha = lambda f: hashlib.sha256(pathlib.Path(f).read_bytes()).hexdigest()
cfg = json.loads(p.read_text(encoding='utf8'))
assert sha(cfg['exe']) == OLD, cfg['exe']
assert sha(SRC) == NEW
assert cfg['env'].get('STRATA_GLM_DSA_XMX') == '1'
NEW_DIR.mkdir(exist_ok=True)
shutil.copy2(SRC, NEW_DIR / 'generate.exe')
assert sha(NEW_DIR / 'generate.exe') == NEW
if not bak.exists():
    shutil.copy2(p, bak)
cfg['exe'] = str(NEW_DIR / 'generate.exe')
p.write_text(json.dumps(cfg, indent=2), encoding='utf8')
print('backup', bak)
print('exe', cfg['exe'], sha(cfg['exe'])[:16], 'DSA_XMX', cfg['env']['STRATA_GLM_DSA_XMX'])
