"""Build generate.exe (the GLM engine) from a patched port tree: every translation unit on its own with icpx, the
objects into one library, then the link. Run inside a shell that has vcvars64 and the oneAPI 2026.0 compiler, MKL,
TBB, UMF, DPL and ocloc environments (build.cmd sets them up).

usage: python build.py --tree <tree> --maya <Maya checkout> --ggml <llama.cpp 3cf0325> --ggml-build <ggml static build>
                       --pr <llama.cpp PR 31428 checkout> [--jobs N] [--only REGEX] [--no-link]

  --tree        the port tree after apply_live_chain.py; objects go to <tree>/compile, the exe to <tree>/link
  --maya        Project Maya v1.1.44 @ 5d20b0e8 (its include/, src/ and third_party/ are on the include path)
  --ggml        llama.cpp @ 3cf0325 (ggml headers)
  --ggml-build  a static ggml-base + ggml-cpu build of that ggml (ggml.cmd), for the CPU ops the engine calls
  --pr          llama.cpp at refs/pull/31428/head (eec5c09), with fused-gemm.hpp patched by apply_live_chain.py;
                src/forkxmx is compiled against its ggml-sycl headers, not the engine's

The flags are the ones the live build used (compile_each.py / link_each.py on the build machine)."""
import argparse, os, re, subprocess, sys, pathlib
from concurrent.futures import ThreadPoolExecutor

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
for a in ('--tree', '--maya', '--ggml', '--ggml-build', '--pr'):
    ap.add_argument(a, required=True, type=pathlib.Path)
ap.add_argument('--jobs', type=int, default=8)
ap.add_argument('--only', default='')
ap.add_argument('--no-link', action='store_true')
a = ap.parse_args()
raw, repo, ggml, gbuild = a.tree.resolve(), a.maya.resolve(), (a.ggml / 'ggml').resolve(), a.ggml_build.resolve()
fork = (a.pr / 'ggml').resolve()
for p in (raw / 'src', repo / 'include', ggml / 'include', fork / 'src' / 'ggml-sycl' / 'fused-gemm.hpp',
          gbuild / 'src' / 'ggml-cpu.lib', gbuild / 'src' / 'ggml-base.lib'):
    if not p.exists():
        sys.exit('missing ' + str(p))

base = ["icpx", "-fsycl", "-std=c++20", "-c", "-fp-model=precise", "-fsycl-default-sub-group-size=32",
        "-Wno-unused-parameter", "-Wno-unused-variable", "-Wno-deprecated-declarations", "-ferror-limit=200",
        "-DSTRATA_VERSION=\"port\"", "-DNOMINMAX", "-D_CRT_SECURE_NO_WARNINGS",
        "-I" + str(raw / "include"), "-I" + str(repo / "include"), "-I" + str(raw / "src"), "-I" + str(repo / "src"),
        "-I" + str(raw / "third_party" / "ggml"), "-I" + str(repo / "third_party" / "ggml"), "-I" + str(repo / "third_party"),
        "-I" + str(ggml / "include"), "-I" + str(ggml / "src")]
A512 = ["-mavx512f", "-mavx512bw", "-mavx512vl", "-mavx512dq", "-mf16c", "-mfma"]
PER_FILE = {   # Maya's CMake per-file CPU flags (STRATA_NATIVE_EXPERTS on: ggml-cpu dot products)
    "expert.cpp": A512 + ["-mavx512vnni", "-mavx512vbmi"], "q2_avx2.cpp": ["-mavx2", "-mfma", "-mf16c"],
    "iq_avx512.cpp": A512 + ["-ffp-contract=off"], "iq_avx2.cpp": ["-mavx2", "-mfma", "-mf16c", "-ffp-contract=off"],
    "iq_avx512_one.cpp": A512 + ["-mavx512vbmi", "-mbmi2", "-ffp-contract=off"], "kq_avx512.cpp": A512}
# src/forkxmx: the PR's grouped GEMM, built with its own headers and defines (its dpct helper and the SYCLomatic dpct
# headers both define namespace dpct); without GGML_SYCL_SUPPORT_XMX the ESIMD path compiles but is never taken
FORK_BASE = ["icpx", "-fsycl", "-std=c++17", "-c", "-O2", "-Wno-narrowing", "-DNOMINMAX", "-D_CRT_SECURE_NO_WARNINGS",
             "-DGGML_SYCL_F16", "-DGGML_SYCL_SUPPORT_XMX", "-DGGML_SYCL_WARP_SIZE=16", "-DGGML_SYCL_XMX_AOT_SG=16",
             "-DMKL_ILP64", "-I" + str(fork / "src" / "ggml-sycl"), "-I" + str(fork / "src"), "-I" + str(fork / "include")]

tus = sorted(p for p in (raw / "src").rglob("*.cpp") if not a.only or re.search(a.only, p.as_posix()))
outd = raw / "compile"; outd.mkdir(exist_ok=True)


def one(p):
    rel = p.relative_to(raw).as_posix()
    log = outd / (rel.replace("/", "__") + ".log")
    extra = PER_FILE.get(p.name, []) + (["-DSTRATA_NATIVE_EXPERTS=1"] if "kernels/cpu" in p.as_posix() else [])
    cmd = (FORK_BASE if "forkxmx" in p.as_posix() else base + extra) + ["-I" + str(p.parent), str(p), "-o", str(log) + ".obj"]
    r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    txt = r.stdout + r.stderr
    log.write_text(txt, encoding="utf-8")
    return rel, r.returncode, len(re.findall(r"\berror:", txt))


with ThreadPoolExecutor(a.jobs) as ex:
    res = list(ex.map(one, tus))
failed = [(rel, e) for rel, rc, e in res if rc]
# exl3.dp.cpp (the EXL3 path, unused by GLM) does not compile and is stubbed: an expected failure
print(f"{len(res)} TUs, {len(res) - len(failed)} compiled; failed: {failed or 'none'}", flush=True)
if [f for f in failed if not f[0].endswith('exl3.dp.cpp')]:
    sys.exit('compile errors - see ' + str(outd))
if a.no_link:
    sys.exit(0)

# every object without a main() goes into one library; generate.exe = its object + the library
out = raw / "link"; out.mkdir(exist_ok=True)
objs = {}
for src in (raw / "src").rglob("*.cpp"):
    obj = outd / (src.relative_to(raw).as_posix().replace("/", "__") + ".log.obj")
    if obj.exists():
        objs[src.stem.replace(".dp", "")] = (obj, bool(re.search(r"^\s*int\s+main\s*\(", src.read_text(errors="replace"), re.M)))
lib = out / "maya_all.lib"
r = subprocess.run(["lib.exe", "/nologo", "/out:" + str(lib)] + [str(o) for o, m in objs.values() if not m],
                   capture_output=True, text=True)
if r.returncode:
    sys.exit('lib failed: ' + (r.stdout + r.stderr)[-2000:])
exe = out / "generate.exe"
r = subprocess.run(["icpx", "-fsycl", "-fsycl-device-code-split=per_kernel", "-Xsycl-target-backend=spir64",
                    "-cl-fp32-correctly-rounded-divide-sqrt -ze-opt-greater-than-4GB-buffer-required",
                    str(objs["generate"][0]), str(lib), "-o", str(exe), "-qmkl=parallel", "-qmkl-sycl-impl=blas",
                    str(gbuild / "src" / "ggml-cpu.lib"), str(gbuild / "src" / "ggml-base.lib"), "-ldxgi", "-ladvapi32"],
                   capture_output=True, text=True, errors="replace")
(out / "generate.link.log").write_text(r.stdout + r.stderr, encoding="utf-8")
unres = sorted(set(re.findall(r"unresolved external symbol (\S+)", r.stdout + r.stderr)))
if r.returncode or unres or not exe.exists():
    sys.exit('link failed: rc %d, unresolved %s' % (r.returncode, unres[:10]))
print('BUILT', exe)
