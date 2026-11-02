"""Compile every migrated translation unit on its own with icpx (spike metric: errors per file).
usage (inside a oneAPI env): python compile_each.py [raw] [jobs]   -> <raw>/compile/<file>.log + summary.tsv"""
import os, re, subprocess, sys, pathlib
from concurrent.futures import ThreadPoolExecutor
raw = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else r"<work>\sycl-raw2")
jobs = int(sys.argv[2]) if len(sys.argv) > 2 else 16
repo = pathlib.Path(r"<work>\maya"); ggml = pathlib.Path(r"<work>\llama.cpp-3cf0325\ggml")
only = os.environ.get("ONLY", "")
tus = sorted(p for p in (raw / "src").rglob("*.cpp") if not only or re.search(only, p.as_posix()))
outd = raw / "compile"; outd.mkdir(exist_ok=True)
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
# src/forkxmx: files from the llama.cpp SYCL fork (its grouped XMX GEMM), built with the fork's own headers and
# defines - its dpct helper and Maya's SYCLomatic dpct headers both define namespace dpct
fork = pathlib.Path(r"<llama.cpp-sycl-fork>\ggml")
FORK_BASE = ["icpx", "-fsycl", "-std=c++17", "-c", "-O2", "-Wno-narrowing", "-DNOMINMAX", "-D_CRT_SECURE_NO_WARNINGS",
             "-DGGML_SYCL_F16", "-DGGML_SYCL_WARP_SIZE=16", "-DGGML_SYCL_XMX_AOT_SG=16", "-DMKL_ILP64",
             "-I" + str(fork / "src" / "ggml-sycl"), "-I" + str(fork / "src"), "-I" + str(fork / "include")]
def one(p):
    rel = p.relative_to(raw).as_posix()
    log = outd / (rel.replace("/", "__") + ".log")
    extra = PER_FILE.get(p.name, []) + (["-DSTRATA_NATIVE_EXPERTS=1"] if "kernels/cpu" in p.as_posix() else [])
    cmd = (FORK_BASE if "forkxmx" in p.as_posix() else base + extra) + ["-I" + str(p.parent), str(p), "-o", str(log) + ".obj"]
    r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    txt = r.stdout + r.stderr
    log.write_text(txt, encoding="utf-8")
    return rel, r.returncode, len(re.findall(r"\berror:", txt)), len(re.findall(r"\bwarning:", txt))
with ThreadPoolExecutor(jobs) as ex:
    res = list(ex.map(one, tus))
with open(outd / "summary.tsv", "w") as f:
    for rel, rc, e, w in sorted(res, key=lambda x: -x[2]):
        f.write(f"{rel}\t{rc}\t{e}\t{w}\n")
ok = sum(1 for r in res if r[1] == 0)
print(f"{len(res)} TUs, {ok} compiled, {sum(r[2] for r in res)} errors total")
