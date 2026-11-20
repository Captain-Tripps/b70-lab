# prof_fndec.py - Flash-Next decode on the served Strata config (CLI, cards level_zero:2,3): plain, or under VTune
# gpu-offload, then the per-kernel table (spill sizes). Prompt = fn-prof-20261116\prompt256.tok.
# usage: python prof_fndec.py <maxnew> <mode: plain|vtune|report>
import json, os, subprocess, sys, time, pathlib, urllib.request

CFG = r"<strata-runtime>\configs\qwen38-flashnext-iq3s-200k.json"
OUT = pathlib.Path(r"<lab>\fn-decprof-20261119"); OUT.mkdir(exist_ok=True)
VT = r"C:\Program Files (x86)\Intel\oneAPI\vtune\latest\bin64\vtune.exe"
TOK = pathlib.Path(r"<lab>\fn-prof-20261116\prompt256.tok")
maxnew, mode = int(sys.argv[1]), sys.argv[2]
extra = dict(a.split("=", 1) for a in sys.argv[3:] if "=" in a)
tag = extra.pop("TAG", "e") if extra else ""
c = json.load(open(CFG, encoding="utf-8"))
r = OUT / ("vtdec%d%s-r" % (maxnew, tag))
if mode == "report":
    with open(OUT / ("vtdec%d%s-tasks.tsv" % (maxnew, tag)), "w") as f:
        subprocess.run([VT, "-report", "hotspots", "-group-by", "computing-task", "-format", "csv",
                        "-csv-delimiter", "tab", "-r", str(r)], stdout=f, stderr=subprocess.STDOUT)
    print("REPORT_DONE"); sys.exit(0)
running = json.load(urllib.request.urlopen("http://<swap>/running", timeout=5))["running"]
if running:
    sys.exit("swap is in use: %s" % running)
env = {k: v for k, v in os.environ.items() if not k.startswith(("STRATA_", "MAYA_", "GGML_", "SYCL_", "ZE_", "UR_", "ONEAPI_DEVICE"))}
env.update(c["env"])
env.update({"ONEAPI_DEVICE_SELECTOR": "level_zero:2,3", "STRATA_DECODE_TIMING": "1"}); env.update(extra)
env["PATH"] = ";".join(c["lib_dirs"]) + ";" + env["PATH"]
gen = [c["exe"]] + c["args"] + ["--tokens-file", str(TOK), "--max-new", str(maxnew), "--greedy"]
cmd = gen if mode == "plain" else [VT, "-collect", "gpu-offload", "-r", str(r), "--"] + gen
t0 = time.time()
p = subprocess.run(cmd, cwd=c["cwd"], env=env, capture_output=True, text=True, errors="replace")
(OUT / ("%s%d%s.log" % (mode, maxnew, tag))).write_text(p.stdout + "\n--- stderr\n" + p.stderr, encoding="utf-8")
keys = ("prompt", "tok/s", "generated", "decode", "error", "Error", "mtp", "MTP")
print("=== %s %d: exit %d, wall %.0f s" % (mode, maxnew, p.returncode, time.time() - t0))
for l in [l for l in (p.stderr + p.stdout).splitlines() if any(k in l for k in keys)][-14:]:
    print("  " + l[:300])
