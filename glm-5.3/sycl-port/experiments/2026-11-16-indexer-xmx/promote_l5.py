"""Point the GLM engine config at the XMX DSA indexer build (L5) and turn its switch on, after a clean soak. Backup kept beside it."""
import hashlib, json, pathlib, shutil, sys
p = pathlib.Path(r'<work>\configs\glm-maya-sycl-128k.json')
bak = p.with_name('glm-maya-sycl-128k.json.bak-predsaxmx-20261116')
OLD = '1a6289326f57f01bc1dd3d8bb378a5b4b0605e3628994409b65de8e5410a33ee'
SRC = pathlib.Path(r'<work>\experiments\claude-glm-l12-20261115\tree4\link\generate.exe')
NEW_DIR = pathlib.Path(r'<work>\rt-glm-esimd-iq2s-dsaxmx-20261116')
NEW = 'f72801f6fefd39b68802ac63c667f56f577b14480434793c0498e72508491ca4'
sha = lambda f: hashlib.sha256(pathlib.Path(f).read_bytes()).hexdigest()
cfg = json.loads(p.read_text(encoding='utf8'))
assert sha(cfg['exe']) == OLD, cfg['exe']
assert sha(SRC) == NEW
assert 'STRATA_GLM_DSA_XMX' not in cfg['env']
NEW_DIR.mkdir(exist_ok=True)
shutil.copy2(SRC, NEW_DIR / 'generate.exe')
assert sha(NEW_DIR / 'generate.exe') == NEW
if not bak.exists():
    shutil.copy2(p, bak)
cfg['exe'] = str(NEW_DIR / 'generate.exe')
cfg['env']['STRATA_GLM_DSA_XMX'] = '1'   # the soaked mode
p.write_text(json.dumps(cfg, indent=2), encoding='utf8')
print('backup', bak)
print('exe', cfg['exe'], sha(cfg['exe'])[:16], 'DSA_XMX', cfg['env']['STRATA_GLM_DSA_XMX'])
