"""One-shot setup: GLM-5.3-Flash (Project Maya's engine, SYCL port) on Intel Arc, Windows.

Fetches the sources at the pinned versions, applies the live changes, builds the engine, packs the model, writes a
server config and runs a smoke test. Run it from setup.cmd, which loads the compiler environment first. Every step is
skipped when its output already exists, so a failed run can be re-run.

usage: setup.cmd --work <folder> --gguf <folder with the 3 Maya-M .gguf shards> [options]

  --work D        everything goes here (sources, build, runtime, pack, config); needs ~15 GB, plus the model if
                  --download is used
  --gguf D        the Maya-M shards (Hugging Face peasantsmith/GLM-5.3-Flash-Maya-GGUF, folder Maya-M, 108 GiB);
                  with --download they are fetched into D first
  --download      fetch the shards with the `hf` CLI (pip install huggingface_hub) and check their sha256
  --base F        the port base archive (file or URL); default: the b70-lab release asset, sha256-checked
  --layer-split, --prefill, --reserve-mb, --slots, --slot-ram-gb, --ram-gb
                  engine settings; the defaults are tuned for 4x Arc Pro B70 32 GB (see RECIPE.md)
  --devices S     ONEAPI_DEVICE_SELECTOR (default level_zero:0,1,2,3)
  --jobs N        parallel compiles (default 8)
  --no-smoke      skip the smoke test (it loads the model on the GPUs: ~75 s, 4 cards)
"""
import argparse, hashlib, json, os, pathlib, shutil, subprocess, sys, tarfile, time, urllib.request

HERE = pathlib.Path(__file__).resolve().parent
PORT = HERE.parent                                  # glm-5.3/sycl-port in this repo
MAYA = ('https://github.com/mw00/project-maya', '5d20b0e8fd7c15fde2a9f2b4eac5e9776883690b')
GGML = ('https://github.com/ggml-org/llama.cpp', '3cf03257f219afbe7334045ff7c6a06ac68c627d')
PR = ('https://github.com/ggml-org/llama.cpp', 'eec5c09cef61885636ee31406855abfe2feb7a44', 'pull/31428/head')
BASE_URL = 'https://github.com/Captain-Tripps/b70-lab/releases/download/glm-sycl-port-base-v1/glm-sycl-port-base-v1.tar.gz'
BASE_SHA = '356d58a6ed8d22ebfbcbc29e35c943831002c4ecfcbb7b1247bc8d85a44065a1'
HF_REPO = 'peasantsmith/GLM-5.3-Flash-Maya-GGUF'
SHARDS = {   # name: sha256 (Hugging Face LFS oids)
    'GLM-5.3-Flash-Maya-M-IQ2_S-00001-of-00003.gguf': '3f740d1b1022b4a0ddad50cd861bb071dd415bde94afa1292d0476641186c638',
    'GLM-5.3-Flash-Maya-M-IQ2_S-00002-of-00003.gguf': '285951d2afa0cd98285b03d0dc4aa68d83daf1a6f4a2594fe40b0cdd27ade485',
    'GLM-5.3-Flash-Maya-M-IQ2_S-00003-of-00003.gguf': 'ebf1ce713f71207747e10eeebed87597969d8b5e1d9dd817420d2c2f7ca51e0e'}
RT_DLLS = ['dnnl.dll', 'libhwloc-15.dll', 'libiomp5md.dll', 'libmmd.dll', 'mkl_core.3.dll', 'mkl_sycl_blas.6.dll',
           'mkl_tbb_thread.3.dll', 'svml_dispmd.dll', 'sycl9.dll', 'tbb12.dll', 'tcm.dll', 'umf.dll',
           'ur_adapter_level_zero.dll', 'ur_adapter_level_zero_v2.dll', 'ur_adapter_opencl.dll', 'ur_loader.dll',
           'ur_win_proxy_loader.dll']

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument('--work', required=True, type=pathlib.Path)
ap.add_argument('--gguf', required=True, type=pathlib.Path)
ap.add_argument('--download', action='store_true')
ap.add_argument('--base', default=BASE_URL)
ap.add_argument('--layer-split', default='14,25,36')
ap.add_argument('--prefill', default='1536')
ap.add_argument('--reserve-mb', default='400')
ap.add_argument('--slots', default='8')
ap.add_argument('--slot-ram-gb', default='12')
ap.add_argument('--ram-gb', default='40')
ap.add_argument('--devices', default='level_zero:0,1,2,3')
ap.add_argument('--jobs', type=int, default=8)
ap.add_argument('--no-smoke', action='store_true')
a = ap.parse_args()
W = a.work.resolve(); W.mkdir(parents=True, exist_ok=True)
G = a.gguf.resolve()
ONEAPI = pathlib.Path(os.environ.get('ONEAPI', r'C:\Program Files (x86)\Intel\oneAPI'))


def step(msg):
    print('\n== ' + msg, flush=True)


def run(cmd, **kw):
    print('  $ ' + ' '.join(str(c) for c in cmd), flush=True)
    r = subprocess.run([str(c) for c in cmd], **kw)
    if r.returncode:
        sys.exit('failed (%d): %s' % (r.returncode, ' '.join(str(c) for c in cmd)))
    return r


def sha256(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 24), b''):
            h.update(b)
    return h.hexdigest()


def checkout(dest, url, sha, ref=None):
    if (dest / '.git').exists():
        head = subprocess.run(['git', '-C', str(dest), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
        if head == sha:
            print('  %s at %s' % (dest.name, sha[:9])); return
        sys.exit('%s exists at %s, expected %s - remove it' % (dest, head[:9], sha[:9]))
    run(['git', 'init', '-q', dest]); run(['git', '-C', dest, 'remote', 'add', 'origin', url])
    if subprocess.run(['git', '-C', str(dest), 'fetch', '-q', '--depth', '1', 'origin', sha]).returncode and ref:
        run(['git', '-C', dest, 'fetch', '-q', '--depth', '1', 'origin', ref])   # some servers only serve named refs
    run(['git', '-C', dest, 'checkout', '-q', 'FETCH_HEAD'])
    head = subprocess.run(['git', '-C', str(dest), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    if head != sha:
        sys.exit('%s: got %s, expected %s (the PR head may have moved)' % (dest, head[:9], sha[:9]))


for tool in ('git', 'icpx', 'cl', 'cmake', 'ninja', 'lib'):
    if not shutil.which(tool):
        sys.exit(tool + ' not on PATH - run this from setup.cmd (VS 18 Build Tools with C++ and CMake, oneAPI 2026.0)')

step('1/8 sources')
checkout(W / 'maya', *MAYA)
checkout(W / 'llama.cpp-3cf0325', *GGML)
checkout(W / 'llama-pr', *PR)

step('2/8 port base')
tree = W / 'tree'
if not (tree / 'src').exists():
    arc = W / 'glm-sycl-port-base.tar.gz'
    if a.base.startswith('http'):
        if not arc.exists():
            print('  download ' + a.base); urllib.request.urlretrieve(a.base, arc)
    else:
        shutil.copyfile(a.base, arc)
    got = sha256(arc)
    if got != BASE_SHA:
        sys.exit('port base sha256 %s, expected %s' % (got, BASE_SHA))
    tmp = W / 'tree.partial'; shutil.rmtree(tmp, ignore_errors=True)
    with tarfile.open(arc) as t:
        t.extractall(tmp, **({'filter': 'data'} if hasattr(tarfile, 'data_filter') else {}))
    os.replace(tmp, tree)
print('  ' + str(tree))

step('3/8 live changes (apply_live_chain.py)')
mark = tree / '.live-chain-applied'
if not mark.exists():
    run([sys.executable, HERE / 'apply_live_chain.py', tree, W / 'llama-pr'])
    mark.write_text('ok')

step('4/8 static ggml (llama.cpp 3cf0325)')
gb = W / 'ggml-build'
if not (gb / 'src' / 'ggml-cpu.lib').exists():
    # ggml/CMakeLists.txt at 3cf0325 configures ggml.pc.in (pkg-config), which the tree does not have; the libraries
    # do not use it, so a placeholder is enough (the live build had the same one)
    pc = W / 'llama.cpp-3cf0325' / 'ggml' / 'ggml.pc.in'
    if not pc.exists():
        pc.write_text('# placeholder (spike)\n')
    run(['cmake', '-S', W / 'llama.cpp-3cf0325' / 'ggml', '-B', gb, '-G', 'Ninja', '-DCMAKE_BUILD_TYPE=Release',
         '-DCMAKE_C_COMPILER=cl', '-DCMAKE_CXX_COMPILER=cl', '-DBUILD_SHARED_LIBS=OFF', '-DGGML_STATIC=ON',
         '-DGGML_OPENMP=OFF', '-DGGML_BACKEND_DL=OFF', '-DGGML_BUILD_TESTS=OFF', '-DGGML_BUILD_EXAMPLES=OFF',
         '-DGGML_NATIVE=OFF', '-DGGML_AVX=ON', '-DGGML_AVX2=ON', '-DGGML_FMA=ON', '-DGGML_F16C=ON', '-DGGML_BMI2=ON',
         '-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreadedDLL'])
    run(['cmake', '--build', gb, '--target', 'ggml-base', 'ggml-cpu'])

step('5/8 engine (build.py)')
exe = tree / 'link' / 'generate.exe'
if not exe.exists():
    run([sys.executable, HERE / 'build.py', '--tree', tree, '--maya', W / 'maya', '--ggml', W / 'llama.cpp-3cf0325',
         '--ggml-build', gb, '--pr', W / 'llama-pr', '--jobs', a.jobs])
# Level Zero loads reliably only from a self-contained folder: the engine plus the oneAPI DLLs it needs
rt = W / 'runtime'; rt.mkdir(exist_ok=True)
shutil.copyfile(exe, rt / 'generate.exe')
bins = [ONEAPI / '2026.0' / 'bin', ONEAPI / 'latest' / 'bin']
for d in RT_DLLS:
    src = next((b / d for b in bins if (b / d).exists()), None)
    if not src:
        sys.exit('%s not found under %s' % (d, ' or '.join(map(str, bins))))
    if not (rt / d).exists():
        shutil.copyfile(src, rt / d)
print('  ' + str(rt))

step('6/8 model')
G.mkdir(parents=True, exist_ok=True)
if a.download and not all((G / n).exists() for n in SHARDS):
    run(['hf', 'download', HF_REPO, '--include', 'Maya-M/*', '--local-dir', G.parent / (G.name + '.hf')])
    for n in SHARDS:
        os.replace(G.parent / (G.name + '.hf') / 'Maya-M' / n, G / n)
for n, want in SHARDS.items():
    p = G / n
    if not p.exists():
        sys.exit('missing %s - pass --download or put the Maya-M shards in %s' % (n, G))
    ok = p.with_name(p.name + '.sha256ok')
    if not ok.exists():
        print('  sha256 ' + n, flush=True)
        if sha256(p) != want:
            sys.exit(n + ': sha256 mismatch')
        ok.write_text(want)
# the engine reads the MTP draft block from the shards next to the pack, so they sit side by side: hard links when
# --work and --gguf are on one drive, else the pack goes into the gguf folder
gm = W / 'glm-m'
try:
    gm.mkdir(exist_ok=True)
    for n in SHARDS:
        if not (gm / n).exists():
            os.link(G / n, gm / n)
except OSError:
    gm = G
pack = gm / 'pack'
venv = W / 'venv'; py = venv / 'Scripts' / 'python.exe'
if not py.exists():
    run([sys.executable, '-m', 'venv', venv])
    run([py, '-m', 'pip', 'install', '-q', 'numpy', 'jinja2', 'tokenizers'])
if not (pack / 'index.txt').exists():
    run([py, W / 'maya' / 'tools' / 'iq_pack.py', '--gguf', gm / list(SHARDS)[0], '--out', pack, '--compat-bf16'],
        cwd=W / 'maya', env=dict(os.environ, STRATA_GGUF_PY=str(W / 'llama.cpp-3cf0325' / 'gguf-py')))
print('  ' + str(pack))

step('7/8 server config')
patch = PORT / 'patches' / '0002-serve-pictures-as-text-without-vision.patch'
if subprocess.run(['git', '-C', str(W / 'maya'), 'apply', '--check', str(patch)], capture_output=True).returncode == 0:
    run(['git', '-C', W / 'maya', 'apply', patch])
cfg_path = W / 'glm-maya-sycl.json'
cfg = json.loads((PORT / 'configs' / 'glm-maya-sycl-128k.json').read_text(encoding='utf-8'))
cfg.pop('vision', None)   # optional CPU vision encoder: see the port README, "Serving it"
cfg['exe'] = str(rt / 'generate.exe')
args = cfg['args']
for flag, val in (('--glm-pack', str(pack)), ('--prefill', a.prefill), ('--layer-split', a.layer_split)):
    args[args.index(flag) + 1] = val
cfg['cwd'] = str(W / 'maya')
cfg['tokenizer'] = str(pack / 'tokenizer')
cfg['log'] = str(W / 'engine.log')
cfg['env'].update({'ONEAPI_DEVICE_SELECTOR': a.devices, 'STRATA_GLM_RESERVE_MB': a.reserve_mb,
                   'STRATA_GLM_SLOTS': a.slots, 'STRATA_GLM_SLOT_RAM_GB': a.slot_ram_gb, 'STRATA_GLM_RAM_GB': a.ram_gb})
cfg['lib_dirs'] = [str(rt)]
cfg_path.write_text(json.dumps(cfg, indent=2), encoding='utf-8')
print('  ' + str(cfg_path))
serve = [str(py), str(W / 'maya' / 'serve' / 'server.py'), '--engine', 'strata', '--config', str(cfg_path),
         '--host', '127.0.0.1', '--port']
(W / 'serve.cmd').write_text('@echo off\r\nset PYTHONUTF8=1\r\n"%s" %s %%1\r\n' % (serve[0], ' '.join(
    '"%s"' % s if ' ' in s else s for s in serve[1:])), encoding='utf-8')
print('  start the server: %s <port>' % (W / 'serve.cmd'))

step('8/8 smoke test')
if a.no_smoke:
    print('  skipped'); sys.exit(0)
port = '18763'
env = dict(os.environ, PYTHONUTF8='1')
log = open(W / 'smoke-server.log', 'w', encoding='utf-8')
p = subprocess.Popen(serve + [port], stdout=log, stderr=subprocess.STDOUT, env=env)
try:
    t0 = time.time()
    while True:
        if p.poll() is not None:
            sys.exit('server exited %d - see %s and %s' % (p.returncode, W / 'smoke-server.log', W / 'engine.log'))
        try:
            urllib.request.urlopen('http://127.0.0.1:%s/health' % port, timeout=5).read(); break
        except Exception:
            if time.time() - t0 > 900:
                sys.exit('server not up after 15 min')
            time.sleep(5)
    req = json.dumps({'model': cfg['model_name'], 'max_tokens': 20, 'chat_template_kwargs': {'enable_thinking': False},
                      'messages': [{'role': 'user', 'content': 'What is 19 * 21? Reply with the number only.'}]}).encode()
    r = urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:%s/v1/chat/completions' % port, req,
                                                      {'Content-Type': 'application/json'}), timeout=600)
    ans = json.loads(r.read())['choices'][0]['message']['content'].strip()
    print('  up in %.0f s; 19 * 21 -> %r' % (time.time() - t0, ans))
    if '399' not in ans:
        sys.exit('smoke test: wrong answer')
finally:
    subprocess.run(['taskkill', '/T', '/F', '/PID', str(p.pid)], capture_output=True)
print('\nSETUP_DONE  config %s  server %s <port>' % (cfg_path, W / 'serve.cmd'))
