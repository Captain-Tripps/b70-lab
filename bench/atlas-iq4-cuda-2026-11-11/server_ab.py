import json, os, pathlib, signal, socket, subprocess, sys, threading, time, urllib.error, urllib.request

root=pathlib.Path('<atlas-home>/experiments/codex-atlas-iq4-20261111')
model='qwen3.8-27b-abliterated-q4'
swap='http://127.0.0.1:8080'
port=19007
out=root/'server-controlled-retry.jsonl'
def http(url, body=None, timeout=5):
    data=None if body is None else json.dumps(body).encode()
    req=urllib.request.Request(url,data=data,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=timeout) as r:
        payload=r.read()
        if not payload.strip(): return None
        try: return json.loads(payload)
        except json.JSONDecodeError: return payload.decode(errors='replace')
def running():return http(swap+'/running')['running']
def slot():return http('http://127.0.0.1:9007/slots')[0]
def stop(p):
    if p and p.poll() is None:
        os.killpg(p.pid,signal.SIGTERM)
        try:p.wait(timeout=20)
        except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
def on_signal(signum,frame):raise KeyboardInterrupt()
signal.signal(signal.SIGTERM,on_signal)

pid=int(sys.argv[1]); cmd=pathlib.Path(f'/proc/{pid}/cmdline').read_bytes().decode().strip('\0').split('\0')
assert cmd[0].endswith('/llama-server') and '--port' in cmd and cmd[cmd.index('--port')+1]=='9007'
cmd[cmd.index('--port')+1]=str(port)
with socket.socket() as sock:
    if sock.connect_ex(('127.0.0.1',port))==0:sys.exit('experiment port already in use')
s=slot()
if s.get('is_processing') or not any(x.get('model')==model and x.get('state')=='ready' for x in running()):sys.exit('Qwen is busy or unavailable')
for sample in range(4):
    r=subprocess.run([sys.executable,str(root/'server_sample.py'),'base-before','9007',str(sample),str(out)],timeout=900)
    if r.returncode:sys.exit('baseline sample failed')
s=slot()
if slot().get('id_task')!=s.get('id_task') or slot().get('is_processing'):sys.exit('Qwen became active')
unloaded=False; p=None; done=threading.Event(); interrupted=threading.Event()
try:
    # The proxy retains ownership; only its idle Qwen instance is unloaded.
    unloaded=True
    http(swap+'/api/models/unload/'+model,{},timeout=90)
    def watch():
        while not done.wait(.4):
            try:
                if any(x.get('model')==model for x in running()):
                    print('Proxy Qwen requested during experiment; aborting',flush=True);interrupted.set();stop(p);return
            except Exception:
                print('Proxy state unavailable; aborting',flush=True);interrupted.set();stop(p);return
    thread=threading.Thread(target=watch,daemon=True);thread.start()
    for arm_index,arm in enumerate(('variant',)):
        if interrupted.is_set():raise RuntimeError('interrupted by proxy activity')
        env=os.environ.copy();env['GGML_CUDA_ALLREDUCE']='internal'
        base='<atlas-home>/llama.cpp-v0.9.0/build-cuda/bin'
        env['LD_LIBRARY_PATH']=(str(root/'variant-2warp')+':' if arm=='variant' else '')+base
        print('Starting',arm_index,arm,flush=True)
        with (root/f'server-{arm_index}-{arm}.log').open('w') as log:
            p=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT,env=env,start_new_session=True)
            deadline=time.monotonic()+900
            while time.monotonic()<deadline:
                if interrupted.is_set() or p.poll() is not None:raise RuntimeError('server startup interrupted or failed')
                try:
                    if http(f'http://127.0.0.1:{port}/health',timeout=2).get('status')=='ok':break
                except Exception:pass
                time.sleep(1)
            else:raise RuntimeError('server startup timed out')
            # Warmup plus three samples, in the same order for every fresh server.
            for sample in range(4):
                if interrupted.is_set():raise RuntimeError('interrupted by proxy activity')
                r=subprocess.run([sys.executable,str(root/'server_sample.py'),arm,str(port),str(arm_index*10+sample),str(out)],timeout=900)
                if r.returncode:raise RuntimeError('sample failed')
            stop(p);p=None
finally:
    done.set();stop(p)
    if unloaded:
        try:
            entries=running()
            if not any(x.get('model')==model for x in entries):
                print('Restoring proxy-managed Qwen',flush=True)
                http(swap+'/v1/chat/completions',{'model':model,'messages':[{'role':'user','content':'Reply OK.'}],'max_tokens':1,'temperature':0},timeout=900)
            entries=running()
            print('Proxy status:',[(x.get('model'),x.get('state')) for x in entries],flush=True)
        except Exception as e:
            print('RESTORE FAILED:',repr(e),flush=True)
            raise
if not interrupted.is_set():
    for sample in range(4):
        r=subprocess.run([sys.executable,str(root/'server_sample.py'),'base-after','9007',str(sample),str(out)],timeout=900)
        if r.returncode:raise RuntimeError('post-restore baseline sample failed')
