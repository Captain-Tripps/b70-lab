#!/usr/bin/env python3
"""Maya GLM port, round 4: glm_fast leftovers. Idempotent."""
import re, sys, pathlib
BS = chr(92)   # a backslash (macro line continuation), spelled out to survive shell quoting
p = pathlib.Path(sys.argv[1]).resolve() / "src/kernels/cuda/glm_fast.dp.cpp"
s = p.read_text(encoding="utf-8", errors="surrogateescape")
t = s
# MLA's sm_80 tensor-core chunk kernel (ldmatrix/mma PTX, as the HIP build): take the stub side
t = re.sub(r"#if defined\(DPCT_COMPATIBILITY_TEMP\) && DPCT_COMPATIBILITY_TEMP >= 800 &&\s*" + re.escape(BS) + r"\n\s*!defined\(STRATA_USE_HIP\)",
           "#if 0   // SYCL: sm_80 ldmatrix/mma PTX not ported (as the HIP build)", t)
# occupancy queries for the hc kernels: dpct could not size their local memory; they use only static local memory
t = t.replace("0 + dpct_placeholder /* total share local memory size */", "0")
# MLA2 expands inside if/else: a braced block followed by ';' breaks the else
t = re.sub(r"(#define MLA2\(H, L, V\)[ \t]*" + re.escape(BS) + r"\n[ \t]*)\{", r"\1do {", t)
t = re.sub(r"(\}\);[ \t]*" + re.escape(BS) + r"\n[ \t]*)\}(\n#define MLA2_HPB)", r"\1} while (0)\2", t)
if t != s:
    p.write_text(t, encoding="utf-8", errors="surrogateescape"); print("  fixed", p.name)
