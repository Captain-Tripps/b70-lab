# gpu_keepalive.py - keep the B70s from looking idle, so Windows does not move a loaded model's VRAM to system RAM
# (~65 s after the last request it did so on 2 of 4 cards, and the next request waited ~50 s for it to come back).
#
# The pinger (a child process: `gpu_keepalive.py ping`) runs a tiny kernel on every card every 15 s and holds
# ~0.24 GB per card for its GPU context. It runs while llama-swap has nothing loaded or every model is ready (v3,
# 2026-11-05: also when idle - idle cards power down and one card's fan blasts to ~3500 rpm on every wake):
# a model that loads next to it fits less (GLM then lends experts for its prompt scratch, and its staged-expert
# prompt path gives invalid routes), so the pinger is stopped - its memory given back - whenever a model starts.
import json, os, subprocess, sys, time, urllib.request

SWAP = os.environ.get("LLAMA_SWAP_RUNNING", "http://127.0.0.1:8080/running")  # llama-swap /running
EVERY = 15.0


def ping():
    import torch
    n = torch.xpu.device_count()
    xs = [torch.zeros(256, device=f"xpu:{i}") for i in range(n)]
    print(time.strftime("%H:%M:%S"), f"pinging {n} devices every {EVERY:g} s", flush=True)
    while True:
        for i, x in enumerate(xs):
            x.add_(1.0)
            torch.xpu.synchronize(i)
        time.sleep(EVERY)


def models_settled():
    """True when llama-swap has nothing loaded or every model is ready; False while one starts or llama-swap does
    not answer."""
    try:
        running = json.load(urllib.request.urlopen(SWAP, timeout=3))["running"]
    except Exception:
        return False
    return all(m.get("state") == "ready" for m in running)


def watch():
    child = None
    while True:
        settled = models_settled()
        if settled and child is None:
            child = subprocess.Popen([sys.executable, "-u", __file__, "ping"])
            print(time.strftime("%H:%M:%S"), "models loaded: pinger started, pid", child.pid, flush=True)
        elif not settled and child is not None:
            child.kill()
            child.wait()
            child = None
            print(time.strftime("%H:%M:%S"), "a model is starting (or none is loaded): pinger stopped", flush=True)
        elif child is not None and child.poll() is not None:
            print(time.strftime("%H:%M:%S"), "pinger exited with", child.returncode, flush=True)
            child = None
        time.sleep(2)


if __name__ == "__main__":
    ping() if sys.argv[1:] == ["ping"] else watch()
