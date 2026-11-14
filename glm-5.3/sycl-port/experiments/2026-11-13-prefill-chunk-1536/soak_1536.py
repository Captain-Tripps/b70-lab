"""30-minute mixed soak of the live GLM build at --prefill 1536 + STRATA_GLM_CKPT_EVERY=65536 (slot carry + checkpoint resume + slot buffer reuse 3) with the live config and server tree
unchanged, port 9080: the 2026-11-12 mixed soak's request mix plus, each cycle, an edit of the long conversation's
last message with new text straight after the 7.7k switch.
Aborts if llama-swap starts a model or free RAM drops below
16 GiB; kills its own tree on exit."""
import ctypes, hashlib, json, os, pathlib, subprocess, sys, threading, time, urllib.request

work = pathlib.Path(os.environ['MAYA_WORK'])   # the engine checkout
root = work / 'experiments' / 'claude-glm-1536-soak-20261113'
run = root / 'soak'
run.mkdir(parents=True, exist_ok=False)
seconds = int(os.environ.get('SLOT_SOAK_SECONDS', '1800'))
PROMOTED = 'de2540a6bb3e5fc0a9b1ba63ae2979b9d927d88e97f3e37c6f2961e2ec3b603b'
LIVE_SERVER = '76185526a58aa06193233b0d9d0f8b7282e6ce888b31004be9cad6dc3140971f'
PROXY = os.environ.get('PROXY_URL', 'http://127.0.0.1:8080')   # the llama-swap proxy
base = 'http://127.0.0.1:9080'


def sha(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


cfg = json.loads((work / 'configs' / 'glm-maya-sycl-128k.json').read_text(encoding='utf8'))
if sha(cfg['exe']) != PROMOTED or sha(work / 'maya' / 'serve' / 'server.py') != LIVE_SERVER:
    sys.exit('live config or server is not the expected one')
if cfg['env'].get('STRATA_GLM_SLOT_CARRY_CKPT') != '1' or cfg['env'].get('STRATA_GLM_SLOT_CKPT_RESUME') != '1' or cfg['env'].get('STRATA_GLM_SLOT_REUSE') != '3':
    sys.exit('live config lacks the carry, resume or reuse switch')
cfg['args'][cfg['args'].index('--prefill') + 1] = '1536'
cfg['env']['STRATA_GLM_CKPT_EVERY'] = '65536'
cfg['log'] = str(run / 'engine.log')
(run / 'config.json').write_text(json.dumps(cfg, indent=2), encoding='utf8')

preflight = r'''$r=Invoke-RestMethod ''' + PROXY + r'''/running -TimeoutSec 5;if (@($r.running).Count -gt 0) {throw 'swap in use'};if (Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(generate|llama-server)\.exe$' }) {throw 'GPU model in use'};$g=@((Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage').CounterSamples | Where-Object { $_.InstanceName -notmatch '0x000159ed' } | ForEach-Object {$_.CookedValue/1GB});if ($g.Count -lt 4 -or ($g | Measure-Object -Maximum).Maximum -gt 1.2) {throw 'GPU not clear'}'''
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
                log.write(json.dumps({'time': time.time(), 'free_bytes': m.free, 'load': m.load}) + '\n'); log.flush()
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
system = {'role': 'system', 'content': 'Be precise.'}


def messages(text, question):
    return [system, {'role': 'user', 'content': text}, {'role': 'assistant', 'content': 'I have read it.'},
            {'role': 'user', 'content': question}]


longtext = source[:390000]; shorttext = source[390000:415000]; mediumtext = source[300000:410000]


def req(label, msgs, cancel=False):
    if abort.is_set():
        raise RuntimeError('watcher aborted')
    body = {'model': 'glm-5.3-flash-maya-sycl', 'messages': msgs, 'max_tokens': 512 if cancel else 64,
            'temperature': 0, 'seed': 1, 'stream': True, 'stream_options': {'include_usage': True},
            'chat_template_kwargs': {'enable_thinking': False}}
    request = urllib.request.Request(base + '/v1/chat/completions', data=json.dumps(body).encode(),
                                     headers={'Content-Type': 'application/json'})
    t = time.perf_counter(); first = None; usage = None; answer = []; events = 0
    with urllib.request.urlopen(request, timeout=1800) as response:
        for raw in response:
            line = raw.decode('utf8', 'replace').strip()
            if not line.startswith('data:'):
                continue
            data = line[5:].strip()
            if data == '[DONE]':
                break
            event = json.loads(data); usage = event.get('usage') or usage
            for ch in event.get('choices', []):
                delta = ch.get('delta') or {}
                part = (delta.get('content') or '') + (delta.get('reasoning_content') or '')
                if part:
                    first = first or time.perf_counter(); answer.append(part); events += 1
            if cancel and events >= 8:
                break
    if first is None or (not cancel and usage is None):
        raise RuntimeError('missing content or usage for ' + label)
    content = ''.join(answer)
    row = {'label': label, 'time': time.time(), 'ttft_s': first - t, 'elapsed_s': time.perf_counter() - t,
           'prompt_tokens': (usage or {}).get('prompt_tokens'),
           'completion_tokens': (usage or {}).get('completion_tokens'),
           'answer_sha256': hashlib.sha256(content.encode()).hexdigest(), 'cancelled': cancel}
    with (run / 'requests.jsonl').open('a', encoding='utf8') as f:
        f.write(json.dumps(row) + '\n')
    print(json.dumps(row), flush=True)
    if cancel:
        t0 = time.monotonic()
        while time.monotonic() - t0 < 180:
            if abort.is_set():
                raise RuntimeError('watcher aborted')
            if not any(x.get('is_processing') for x in read_json(base + '/slots')):
                break
            time.sleep(1)
        else:
            raise RuntimeError('cancelled request did not clear within 180 seconds')
        print('CANCEL_CLEARED seconds=', round(time.monotonic() - t0, 2), flush=True)
    return content


try:
    with (run / 'server.log').open('wb') as out:
        proc = subprocess.Popen([sys.executable, '-m', 'serve.server', '--engine', 'strata', '--config',
                                 str(run / 'config.json'), '--host', '127.0.0.1', '--port', '9080'],
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
        start = time.monotonic(); print('READY seconds=', seconds, flush=True)
        req('long-prime', messages(longtext, 'Give a short status for review 0.'))
        cycle = 0
        while time.monotonic() - start < seconds:
            cycle += 1
            for n in (1, 2, 3):
                req(f'{cycle}:long-edit-{n}', messages(longtext, f'Give a short status for review {n}.'))
            req(f'{cycle}:short-switch', messages(shorttext, 'Summarize this briefly.'))
            req(f'{cycle}:straight-edit', messages(longtext, f'Give a short status for review {1000 + cycle}.'))
            longmessages = messages(longtext, 'Give a short status for review 3.')
            reply = req(f'{cycle}:long-return', longmessages)
            req(f'{cycle}:append', longmessages + [{'role': 'assistant', 'content': reply},
                                                   {'role': 'user', 'content': 'Continue with one more brief observation.'}])
            if cycle % 3 == 0:
                req(f'{cycle}:medium-switch', messages(mediumtext, 'Summarize this briefly.'))
            if cycle % 4 == 0:
                for j in range(2):
                    req(f'{cycle}:extra-{j}', messages(source[415000 + j * 20000:435000 + j * 20000],
                                                        f'Give brief observation {j}.'))
            if cycle % 5 == 0:
                c = [{'role': 'user', 'content': 'List 100 useful practices for testing software services, with explanations.'}]
                req(f'{cycle}:cancel', c, True); req(f'{cycle}:retry', c)
            print('CYCLE', cycle, 'elapsed_s', round(time.monotonic() - start, 1), flush=True)
        print('SOAK_COMPLETE cycles=', cycle, 'elapsed_s=', round(time.monotonic() - start, 1), flush=True)
finally:
    done.set()
    kill_tree()
    if proc:
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
    print('SERVER_STOPPED', flush=True)
