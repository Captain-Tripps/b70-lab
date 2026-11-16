"""Point the GLM engine config at the ESIMD grouped-GEMM build with the IQ2_S format (L12, gate/up), after a clean soak. Backup kept beside it."""
import hashlib, json, pathlib, shutil, sys
p = pathlib.Path(r'<work>\configs\glm-maya-sycl-128k.json')
bak = p.with_name('glm-maya-sycl-128k.json.bak-preiq2s-20261116')
OLD = '7112581dd32857efc52d2504fc6607ce68194dbc368820f391960d436ecbdf5a'
SRC = pathlib.Path(r'<work>\experiments\claude-glm-l12-20261115\tree2\link\generate.exe')
NEW_DIR = pathlib.Path(r'<work>\rt-glm-esimd-iq2s-20261116')
NEW = '1a6289326f57f01bc1dd3d8bb378a5b4b0605e3628994409b65de8e5410a33ee'
sha = lambda f: hashlib.sha256(pathlib.Path(f).read_bytes()).hexdigest()
cfg = json.loads(p.read_text(encoding='utf8'))
assert sha(cfg['exe']) == OLD, cfg['exe']
assert sha(SRC) == NEW
NEW_DIR.mkdir(exist_ok=True)
shutil.copy2(SRC, NEW_DIR / 'generate.exe')
assert sha(NEW_DIR / 'generate.exe') == NEW
if not bak.exists():
    shutil.copy2(p, bak)
cfg['exe'] = str(NEW_DIR / 'generate.exe')
assert 'GGML_SYCL_MMID_ESIMD' not in cfg['env']   # default 1, the soaked mode
p.write_text(json.dumps(cfg, indent=2), encoding='utf8')
print('backup', bak)
print('exe', cfg['exe'], sha(cfg['exe'])[:16])
