"""Prompt-read screen on the live GLM build: checkpoint spacing (STRATA_GLM_CKPT_EVERY) and layer split.
usage: screen_pf.py <arm> <ckpt_every|default> <split|default>
Live executable, live config and live server tree, port 9079 (never the live 9063). Each arm: warm-up, a cold
~42k read, a cold ~115k read, two 512-token decodes. Aborts if llama-swap starts a model or free RAM drops below
16 GiB; kills its own tree on exit."""
import ctypes, hashlib, json, os, pathlib, re, subprocess, sys, threading, time, urllib.request

work = pathlib.Path(os.environ['MAYA_WORK'])   # the engine checkout
root = work / 'experiments' / 'claude-glm-chunk-screen-20261113'
arm, ckpt, split, chunk = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
run = root / arm
run.mkdir(parents=True, exist_ok=False)
LIVE_EXE = 'de2540a6bb3e5fc0a9b1ba63ae2979b9d927d88e97f3e37c6f2961e2ec3b603b'
LIVE_SERVER = '76185526a58aa06193233b0d9d0f8b7282e6ce888b31004be9cad6dc3140971f'
PROXY = os.environ.get('PROXY_URL', 'http://127.0.0.1:8080')   # the llama-swap proxy
base = 'http://127.0.0.1:9079'


def sha(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


cfg = json.loads((work / 'configs' / 'glm-maya-sycl-128k.json').read_text(encoding='utf8'))
if sha(cfg['exe']) != LIVE_EXE or sha(work / 'maya' / 'serve' / 'server.py') != LIVE_SERVER:
    sys.exit('live config or server is not the expected one')
cfg['log'] = str(run / 'engine.log')
if ckpt != 'default':
    cfg['env']['STRATA_GLM_CKPT_EVERY'] = ckpt
if split != 'default':
    i = cfg['args'].index('--layer-split')
    cfg['args'][i + 1] = split
if chunk != 'default':
    cfg['args'][cfg['args'].index('--prefill') + 1] = chunk
(run / 'config.json').write_text(json.dumps(cfg, indent=2), encoding='utf8')

preflight = r'''$r=Invoke-RestMethod ''' + PROXY + r'''/running -TimeoutSec 5;if (@($r.running).Count -gt 0) {throw 'swap in use'};if (Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(generate|llama-server)\.exe$' }) {throw 'GPU model in use'}'''
subprocess.run(['powershell.exe', '-NoProfile', '-Command', preflight], check=True, timeout=60)
env = {k: v for k, v in os.environ.items()
       if not k.upper().startswith(('MAYA_', 'STRATA_', 'SYCL_', 'ZE_', 'ZES_', 'UR_', 'ONEAPI_DEVICE_SELECTOR'))}
env['PYTHONUTF8'] = '1'


class Mem(ctypes.Structure):
    _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong), ('total', ctypes.c_ulonglong),
                ('free', ctypes.c_ulonglong), ('totalpage', ctypes.c_ulonglong), ('freepage', ctypes.c_ulonglong),
                ('totalvirtual', ctypes.c_ulonglong), ('freevirtual', ctypes.c_ulonglong),
                ('freeextended', ctypes.c_ulonglong)]


def read_json(url, timeout=5):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


done = threading.Event(); abort = threading.Event(); abort_reason = []; proc = None


def kill_tree():
    if proc and proc.poll() is None:
        subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def watcher():
    with (run / 'memory.jsonl').open('w', encoding='utf8') as log:
        while not done.is_set():
            m = Mem(); m.length = ctypes.sizeof(m)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
                log.write(json.dumps({'time': time.time(), 'free_bytes': m.free}) + '\n'); log.flush()
                if m.free < 16 * 1024 ** 3:
                    abort_reason.append('physical memory below 16 GiB'); abort.set()
            try:
                if read_json(PROXY + '/running').get('running'):
                    abort_reason.append('proxy started a model'); abort.set()
            except Exception:
                abort_reason.append('proxy state unavailable'); abort.set()
            if abort.is_set():
                print('ABORT', abort_reason[-1], flush=True)
                kill_tree()
                return
            done.wait(2)


source = (work / 'long_body.txt').read_text(encoding='utf8')


def req(label, content, max_tokens, think=False):
    if abort.is_set():
        raise RuntimeError('watcher aborted')
    body = {'model': 'glm-5.3-flash-maya-sycl', 'messages': [{'role': 'user', 'content': content}],
            'max_tokens': max_tokens, 'temperature': 0, 'seed': 1}
    if not think:
        body['chat_template_kwargs'] = {'enable_thinking': False}
    t = time.perf_counter()
    r = json.load(urllib.request.urlopen(urllib.request.Request(base + '/v1/chat/completions',
                  json.dumps(body).encode(), {'Content-Type': 'application/json'}), timeout=1800))
    tm = r.get('timings', {}); msg = r['choices'][0]['message']
    text = (msg.get('content') or '') + (msg.get('reasoning_content') or '')
    row = {'arm': arm, 'label': label, 'wall_s': round(time.perf_counter() - t, 3),
           'prompt_n': tm.get('prompt_n'), 'prompt_ms': tm.get('prompt_ms'), 'prompt_tps': tm.get('prompt_per_second'),
           'cache_n': tm.get('cache_n'), 'gen_n': tm.get('predicted_n'), 'gen_tps': tm.get('predicted_per_second'),
           'draft': [tm.get('draft_n'), tm.get('draft_n_accepted')],
           'answer_sha256': hashlib.sha256(text.encode()).hexdigest(), 'answer_head': text[:80]}
    with (run / 'requests.jsonl').open('a', encoding='utf8') as f:
        f.write(json.dumps(row) + '\n')
    print(json.dumps(row), flush=True)


try:
    with (run / 'server.log').open('wb') as out:
        proc = subprocess.Popen([sys.executable, '-m', 'serve.server', '--engine', 'strata', '--config',
                                 str(run / 'config.json'), '--host', '127.0.0.1', '--port', '9079'],
                                cwd=str(work / 'maya'), env=env, stdout=out, stderr=subprocess.STDOUT,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        threading.Thread(target=watcher, daemon=True).start()
        for _ in range(400):
            if abort.is_set() or proc.poll() is not None:
                raise RuntimeError('server startup failed or aborted')
            try:
                if read_json(base + '/v1/models', 2):
                    break
            except Exception:
                time.sleep(1)
        else:
            raise RuntimeError('server startup timeout')
        print('READY', arm, flush=True)
        # distinct openings so no request continues another's cached prefix
        req('warm-8k', 'Warm-up W.\n' + source[300000:330000] + '\n\nIn one sentence, what is this text about?', 40)
        req('cold-42k', 'Read A.\n' + source[:150000] + '\n\nIn one sentence, what is this text about?', 40)
        req('cold-115k', 'Read B.\n' + source[:390000] + '\n\nIn one sentence, what is this text about?', 40)
        for i in (1, 2):
            req(f'decode-{i}', f'Run {i}. Write a detailed 600-word essay about the history of the printing press.', 512)
        print('ARM_COMPLETE', arm, flush=True)
finally:
    done.set()
    kill_tree()
    if proc:
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
    lines = [l for l in (run / 'engine.log').read_text(encoding='utf8', errors='replace').splitlines()
             if re.search(r'glm prefill: \d+ tokens in|glm vram: prompt|chunk is|does not fit|error|chunks of|incomplete|token by token', l)] \
        if (run / 'engine.log').exists() else []
    (run / 'prefill-lines.txt').write_text('\n'.join(lines), encoding='utf8')
    # experts copied in while a prompt ran: the per-chunk stage lines' pcie / ram / disk / vram totals
    totals = {'chunk_lines': 0, 'pcie': 0.0, 'ram': 0.0, 'disk': 0.0, 'vram': 0.0}
    stage = re.compile(r'pcie ([0-9.]+) GB \(ram ([0-9.]+), disk ([0-9.]+)\) \+ ([0-9.]+) GB vram')
    if (run / 'engine.log').exists():
        for l in (run / 'engine.log').read_text(encoding='utf8', errors='replace').splitlines():
            m = stage.search(l)
            if m:
                totals['chunk_lines'] += 1
                for k, v in zip(('pcie', 'ram', 'disk', 'vram'), m.groups()):
                    totals[k] += float(v)
    (run / 'staging.json').write_text(json.dumps(totals), encoding='utf8')
    print('STAGING', arm, json.dumps(totals), flush=True)
    print('SERVER_STOPPED', arm, flush=True)
