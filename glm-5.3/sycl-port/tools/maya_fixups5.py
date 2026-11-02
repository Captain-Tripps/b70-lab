#!/usr/bin/env python3
"""Maya GLM port, round 5: launchers must never pick a tensor-core kernel whose body is stubbed in this port.
dpct's get_major_version() is 3 on OpenCL (every arm already declines) but parses the device version string, which
on Level Zero is an IP version (>= 7) - so decline explicitly. Audit: all 14 launch paths checked. Idempotent."""
import re, sys, pathlib
root = pathlib.Path(sys.argv[1]).resolve()
TAG = "// SYCL: tensor-core kernel is a stub in this port - decline"

def patch(rel, edits):
    p = root / rel
    s = p.read_text(encoding="utf-8", errors="surrogateescape")
    t = s
    for name, pat, value in edits:
        n = 0
        def repl(m):
            nonlocal n
            if TAG in t[m.end():m.end() + 200]:
                return m.group(0)
            n += 1
            line_start = t.rfind("\n", 0, m.start()) + 1
            ind = re.match(r"[ \t]*", t[line_start:]).group(0)
            return m.group(0) + "\n" + ind + m.group("var") + " = " + value + "; " + TAG
        t = re.sub(pat, repl, t, flags=re.S)
        print(f"  {rel} {name}: {n} site(s)")
    if t != s:
        p.write_text(t, encoding="utf-8", errors="surrogateescape")

B = "src/kernels/cuda/glm_batch.dp.cpp"; F = "src/kernels/cuda/glm_fast.dp.cpp"
patch(B, [
    # A: mla_attn - tc / tc2 / v70 / tc_reg / mma prompt kernels -> the F32 kernel
    ("A mla_attn", r"fits\(\(const void \*\)mla_attn_tc_reg_kernel_wrapper, kTcRegSmem\)\)\s*(?P<var>tc_ok\[dev\]) = 2;", "-1"),
    # B: mla_decode_v70 -> the F32 split chunks
    ("B mla_decode_v70", r"(?<![\w])(?P<var>ok\[dev\]) =[^;]*?major == 7[^;]*?;", "-1"),
    # C: dsa_score -> the tiled FP32 kernel
    ("C dsa_score", r"(?P<var>tc_dev\[dev\]) = major >= 7 && 0 == 0 \? 1 : -1;", "-1"),
])
patch(F, [
    # D: mma_arch() - Q4_K / Q8_0 jobs -> the dp4a column loops
    ("D mma_arch", r"(?P<var>cache\[dev\]) = major >= 8 && !off \? 1 : 2;", "2"),
    # E: mma_ok() - the STRATA_GLM_MV_MMA opt-in
    ("E mma_ok", r"(?P<var>cache\[dev\]) = std::atoi\(v\) != 0 && major >= 8 \? 1 : 2;", "2"),
    # F: mla_mma_on() - mla_split_mma_kernel -> the F32 chunks
    ("F mla_mma_on", r"bool (?P<var>on) =\s*major >= 8[^;]*;", "false"),
])
