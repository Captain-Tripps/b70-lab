"""A RAM slot carrying its turn-start checkpoint (STRATA_GLM_SLOT_CARRY_CKPT), one candidate executable, arm off / on.
The live GLM config otherwise, the turn-trace server copy, port 9079, never the live 9063. Aborts if llama-swap
starts a model or free RAM drops below 16 GiB; kills its own tree on exit.  usage: run_screen.py <arm> off|on"""
import ctypes, hashlib, json, os, pathlib, subprocess, sys, threading, time, urllib.request

work = pathlib.Path(r'D:\maya-sycl')
root = work / 'experiments' / 'codex-glm-ckpt-carry-20261113'
run = root / sys.argv[1]
keep = {'off': False, 'on': True}[sys.argv[2]]
run.mkdir(parents=True, exist_ok=False)
overlay = work / 'experiments' / 'codex-glm-turn-trace-20261113' / 'overlay'
OVERLAY_SERVER = 'a304ed851922a23964a46a277771a2614a8f8bf6a370c6554eacb237eb6eea8f'
PROMOTED = 'f89820fe92e49ffa6e563b538d5dc5aebe9b246e95d29d523f3e76f0ed0acea8'
candidate = root / 'tree' / 'link' / 'generate.exe'
CANDIDATE = (root / 'candidate.sha256').read_text().strip()
PROXY = 'http://100.89.126.50:8080'
base = 'http://127.0.0.1:9079'

def sha(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()

cfg = json.loads((work / 'configs' / 'glm-maya-sycl-128k.json').read_text(encoding='utf8'))
if sha(cfg['exe']) != PROMOTED:
    sys.exit('live config does not point at the promoted executable')
if sha(candidate) != CANDIDATE or sha(overlay / 'serve' / 'server.py') != OVERLAY_SERVER:
    sys.exit('unexpected candidate executable or server copy')
cfg['exe'] = str(candidate)
cfg['log'] = str(run / 'engine.log')
cfg['env']['STRATA_GLM_SLOT_TIMING'] = '1'
if keep:
    cfg['env']['STRATA_GLM_SLOT_CARRY_CKPT'] = '1'
(run / 'config.json').write_text(json.dumps(cfg, indent=2), encoding='utf8')

preflight = r'''$r=Invoke-RestMethod http://100.89.126.50:8080/running -TimeoutSec 5;if (@($r.running).Count -gt 0) {throw 'swap in use'};if (Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(generate|llama-server)\.exe$' }) {throw 'GPU model in use'};$g=@((Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage').CounterSamples | Where-Object { $_.InstanceName -notmatch '0x000159ed' } | ForEach-Object {$_.CookedValue/1GB});if ($g.Count -lt 4 -or ($g | Measure-Object -Maximum).Maximum -gt 1.2) {throw 'GPU not clear'}'''
subprocess.run(['powershell.exe', '-NoProfile', '-Command', preflight], check=True, timeout=60)

env = {k: v for k, v in os.environ.items()
       if not k.upper().startswith(('MAYA_', 'STRATA_', 'SYCL_', 'ZE_', 'ZES_', 'UR_', 'ONEAPI_DEVICE_SELECTOR'))}
env['PYTHONUTF8'] = '1'
env['MAYA_TURN_TRACE'] = '1'


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


longtext = source[:390000]; shorttext = source[390000:415000]


def req(label, msgs):
    if abort.is_set():
        raise RuntimeError('watcher aborted')
    body = {'model': 'glm-5.3-flash-maya-sycl', 'messages': msgs, 'max_tokens': 64, 'temperature': 0, 'seed': 1,
            'stream': True, 'stream_options': {'include_usage': True},
            'chat_template_kwargs': {'enable_thinking': False}}
    request = urllib.request.Request(base + '/v1/chat/completions', data=json.dumps(body).encode(),
                                     headers={'Content-Type': 'application/json'})
    t = time.perf_counter(); first = None; usage = None; answer = []
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
                    first = first or time.perf_counter(); answer.append(part)
    if first is None or usage is None:
        raise RuntimeError('missing content or usage for ' + label)
    row = {'label': label, 'time': time.time(), 'ttft_s': first - t, 'elapsed_s': time.perf_counter() - t,
           'prompt_tokens': usage.get('prompt_tokens'), 'completion_tokens': usage.get('completion_tokens'),
           'answer_sha256': hashlib.sha256(''.join(answer).encode()).hexdigest()}
    with (run / 'requests.jsonl').open('a', encoding='utf8') as f:
        f.write(json.dumps(row) + '\n')
    print(json.dumps(row), flush=True)


try:
    with (run / 'server.log').open('wb') as out:
        proc = subprocess.Popen([sys.executable, '-m', 'serve.server', '--engine', 'strata', '--config',
                                 str(run / 'config.json'), '--host', '127.0.0.1', '--port', '9079'],
                                cwd=str(overlay), env=env, stdout=out, stderr=subprocess.STDOUT,
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
        start = time.monotonic(); print('READY', flush=True)
        req('long-prime', messages(longtext, 'Give a short status for review 0.'))
        novel = 100
        for cycle in (1, 2, 3, 4):
            for n in (1, 2, 3):
                req(f'{cycle}:long-edit-{n}', messages(longtext, f'Give a short status for review {n}.'))
            for _ in range(2):
                novel += 1
                req(f'{cycle}:novel-edit-{novel}', messages(longtext, f'Give a short status for review {novel}.'))
            req(f'{cycle}:short-switch', messages(shorttext, 'Summarize this briefly.'))
            longmessages = messages(longtext, 'Give a short status for review 3.')
            req(f'{cycle}:long-return', longmessages)
            req(f'{cycle}:append', longmessages + [{'role': 'assistant', 'content': 'Status noted.'},
                                                   {'role': 'user', 'content': f'Continue with observation {cycle}.'}])
            print('CYCLE', cycle, 'elapsed_s', round(time.monotonic() - start, 1), flush=True)
        print('RUN_COMPLETE elapsed_s', round(time.monotonic() - start, 1), flush=True)
finally:
    done.set()
    kill_tree()
    if proc:
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
    print('SERVER_STOPPED', flush=True)
