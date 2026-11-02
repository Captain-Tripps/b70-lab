# start_ab.py - fresh-start test of a served Strata config: N starts, 4 prompts each, median decode per start.
# usage: python start_ab.py OUT.jsonl STARTS
# env: STRATA_CFG (engine config), STRATA_SERVER (sycl/serve/server_intel.py), STRATA_PY (python, default this one),
#      GPUSTATE (a tool printing "GPU n pci ..." / "freq gpu actual N" lines; optional clock sampling),
#      SEL (ONEAPI_DEVICE_SELECTOR, default level_zero:2,3), FLOOR (STRATA_SPEED_GUARD_MIN for the test, 0 = guard off),
#      CLEAN=1 (stop the engine with POST /v1/unload before ending the server), PURGE=1 (purge_standby.ps1 before each start).
import json, os, re, subprocess, sys, threading, time, uuid, urllib.request, statistics

HERE = os.path.dirname(os.path.abspath(__file__))
RUN = os.environ.get("RUN_DIR", HERE)


def freq_sampler(stop, out):
    if not os.environ.get("GPUSTATE"):
        return
    while not stop.is_set():
        r = subprocess.run([os.environ["GPUSTATE"]], capture_output=True, text=True)
        cur = None
        for l in r.stdout.splitlines():
            m = re.match(r"GPU (\d)\s+pci (\S+)", l)
            if m:
                cur = m.group(2)
            m = re.search(r"freq gpu\s+actual (\d+)", l)
            if m and cur:
                out.setdefault(cur, []).append(int(m.group(1)))
        time.sleep(0.5)

CFG = os.environ["STRATA_CFG"]            # the served engine config (JSON)
PY = os.environ.get("STRATA_PY", sys.executable)
SRV = os.environ["STRATA_SERVER"]         # <strata>\sycl\serve\server_intel.py
PORT = int(os.environ.get("PORT", "8090"))
ARMS = {"g": {"STRATA_SPEED_GUARD_MIN": os.environ.get("FLOOR", "90"), "STRATA_SPEED_GUARD_TRIES": os.environ.get("TRIES", "3")}}
PROMPTS = {
    "code": "Write a Python function that parses an ISO 8601 date string without using datetime.fromisoformat, with three pytest tests.",
    "prose": "Write the opening two paragraphs of a mystery story set in a lighthouse during a storm.",
    "explain": "Explain how a hash table handles collisions, comparing chaining and open addressing, in about 200 words.",
    "summary": "Summarize the causes and main events of the French Revolution in eight bullet points.",
}
out_path, n = sys.argv[1], int(sys.argv[2])
base_url = "http://127.0.0.1:%d" % PORT
out = open(out_path, "a", encoding="utf-8")


def make_cfg(arm, extra):
    c = json.load(open(CFG, encoding="utf-8"))
    c["env"].update(extra)
    c["log"] = os.path.join(RUN, "start-ab-%s.log" % arm)
    p = os.path.join(RUN, "start-ab-%s.json" % arm)
    json.dump(c, open(p, "w", encoding="utf-8"), indent=1)
    return p, c["log"]


def ask(text, max_tokens):
    body = json.dumps({"model": "x", "messages": [{"role": "user", "content": text}], "max_tokens": max_tokens,
                       "temperature": 0, "cache_prompt": False,
                       "chat_template_kwargs": {"enable_thinking": False}}).encode()
    req = urllib.request.Request(base_url + "/v1/chat/completions", body, {"Content-Type": "application/json"})
    t0 = time.time()
    r = json.load(urllib.request.urlopen(req, timeout=1800))
    return r, time.time() - t0


def cpu_s():
    r = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-Process strata -EA SilentlyContinue | Measure-Object CPU -Sum).Sum"],
                       capture_output=True, text=True)
    try: return float(r.stdout.strip() or 0)
    except ValueError: return -1.0


def healthy():
    try:
        urllib.request.urlopen(base_url + "/health", timeout=3)
        return True
    except Exception:
        return False


summary = {a: [] for a in ARMS}
for i in range(n):
    for arm, extra in ARMS.items():
        cfg, log = make_cfg(arm, extra)
        env = dict(os.environ, ONEAPI_DEVICE_SELECTOR=os.environ.get("SEL", "level_zero:2,3"), PYTHONUTF8="1",
                   STRATA_ALLOWED_HOSTS="localhost")
        if os.environ.get("PURGE") == "1":               # empty the standby list (file cache) before the start
            pr = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                 os.path.join(HERE, "purge_standby.ps1")], capture_output=True, text=True)
            print("start %d %s" % (i + 1, pr.stdout.strip().splitlines()[-1] if pr.stdout.strip() else pr.stderr[-200:]), flush=True)
        lsz = os.path.getsize(log) if os.path.exists(log) else 0
        p = subprocess.Popen([PY, SRV, "--engine", "strata", "--config", cfg, "--host", "127.0.0.1", "--port", str(PORT)],
                             env=env, stdout=subprocess.DEVNULL, stderr=open(os.path.join(RUN, "start-ab-server.err"), "w"))
        try:
            t0 = time.time()
            while not healthy():
                if p.poll() is not None or time.time() - t0 > 900:
                    raise RuntimeError("server did not come up (exit %s after %.0f s)" % (p.poll(), time.time() - t0))
                time.sleep(2)
            load_s = time.time() - t0
            gl = [l.strip() for l in open(log, encoding="utf-8", errors="replace").read()[lsz:].splitlines() if "[speed-guard]" in l]
            print("start %d load %.0f s  %s" % (i + 1, load_s, " | ".join(x.split(": ", 1)[1] for x in gl)), flush=True)
            r, w = ask("Say OK.", 8)
            time.sleep(3)
            c0 = cpu_s(); time.sleep(10); idle = (cpu_s() - c0) / 10.0
            c0 = cpu_s(); tr0 = time.time()
            fq = {}; stop = threading.Event(); th = threading.Thread(target=freq_sampler, args=(stop, fq)); th.start()
            rates = []
            for name, pr in PROMPTS.items():
                r, w = ask("[request %s]\n%s" % (uuid.uuid4().hex[:12], pr), 400)
                t = r.get("timings", {})
                rec = {"arm": arm, "start": i + 1, "prompt": name, "tg": t.get("predicted_per_second"),
                       "n": (r.get("usage") or {}).get("completion_tokens"), "draft_n": t.get("draft_n"),
                       "draft_acc": t.get("draft_n_accepted"),
                       "head": (r["choices"][0]["message"].get("content") or "")[:80]}
                out.write(json.dumps(rec) + "\n"); out.flush()
                if rec["tg"]:
                    rates.append(rec["tg"])
            stop.set(); th.join()
            busy = (cpu_s() - c0) / (time.time() - tr0)
            fqs = " ".join("%s:%d/%d" % (k, min(v), statistics.median(v)) for k, v in sorted(fq.items()))
            med = statistics.median(rates) if rates else 0
            summary[arm].append(med)
            print("start %d %-5s median %.1f  cpu idle %.1f cores, decoding %.1f cores  MHz %s  %s" % (i + 1, arm, med, idle, busy, fqs, [round(x, 1) for x in rates]), flush=True)
        except Exception as e:
            print("start %d %-5s FAILED: %s" % (i + 1, arm, e), flush=True)
        finally:
            if os.environ.get("CLEAN") == "1":          # QUIT the engine through the server first, then end the server
                t1 = time.time()
                try:
                    rq = urllib.request.Request(base_url + "/v1/unload", b"{}", {"Content-Type": "application/json"})
                    res = urllib.request.urlopen(rq, timeout=120).read()[:80]
                except Exception as e:
                    res = "unload failed: %s" % e
                while time.time() - t1 < 90:
                    pr = subprocess.run(["tasklist", "/FI", "IMAGENAME eq strata.exe", "/NH"], capture_output=True, text=True)
                    if "strata.exe" not in pr.stdout:
                        break
                    time.sleep(1)
                print("start %d clean stop: %s, engine gone after %.0f s: %s" % (i + 1, res, time.time() - t1,
                      "strata.exe" not in pr.stdout), flush=True)
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
            time.sleep(8)
for arm, v in summary.items():
    if v:
        print("== %s: starts %s  median-of-medians %.1f" % (arm, [round(x, 1) for x in v], statistics.median(v)), flush=True)
