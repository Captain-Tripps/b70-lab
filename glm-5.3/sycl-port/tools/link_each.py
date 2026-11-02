"""Link Maya GLM SYCL test programs from compile_each.py's objects (spike).
usage (oneAPI + vcvars env): python link_each.py <raw> target [target ...]
  target = a source stem with a main(), e.g. glm_layer_parity. Every object WITHOUT a main() goes into
  <raw>/link/maya_all.lib (so only what a program needs is pulled in); each program = its object + that lib."""
import re, subprocess, sys, pathlib
raw = pathlib.Path(sys.argv[1]); targets = sys.argv[2:]
comp = raw / "compile"; out = raw / "link"; out.mkdir(exist_ok=True)
objs = {}
for src in (raw / "src").rglob("*.cpp"):
    rel = src.relative_to(raw).as_posix()
    obj = comp / (rel.replace("/", "__") + ".log.obj")
    if obj.exists():
        objs[src.stem.replace(".dp", "")] = (obj, bool(re.search(r"^\s*int\s+main\s*\(", src.read_text(errors="replace"), re.M)))
lib = out / "maya_all.lib"
libobjs = [str(o) for o, has_main in objs.values() if not has_main]
r = subprocess.run(["lib.exe", "/nologo", "/out:" + str(lib)] + libobjs, capture_output=True, text=True)
print("lib:", len(libobjs), "objects ->", lib.name, "rc", r.returncode, (r.stdout + r.stderr)[-2000:])
link = ["icpx", "-fsycl", "-fsycl-device-code-split=per_kernel",
        "-Xsycl-target-backend=spir64", "-cl-fp32-correctly-rounded-divide-sqrt -ze-opt-greater-than-4GB-buffer-required"]
for t in targets:
    obj, _ = objs[t]
    exe = out / (t + ".exe"); log = out / (t + ".link.log")
    mapf = ["-Xlinker", "/MAP:" + str(out / (t + ".map"))] if __import__("os").environ.get("MAYA_LINK_MAP") else []
    r = subprocess.run(link + mapf + [str(obj), str(lib), "-o", str(exe), "-qmkl=parallel", "-qmkl-sycl-impl=blas",
                        r"<work>\ggml-build\src\ggml-cpu.lib", r"<work>\ggml-build\src\ggml-base.lib", "-ldxgi", "-ladvapi32"],
                       capture_output=True, text=True, errors="replace")
    log.write_text(r.stdout + r.stderr, encoding="utf-8")
    unres = sorted(set(re.findall(r"unresolved external symbol (\S+)", r.stdout + r.stderr)))
    print(f"{t}: rc {r.returncode}, {len(unres)} unresolved", *unres[:15], sep="\n  ")
