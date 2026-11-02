#!/usr/bin/env python3
"""Maya GLM port, round 3: ggml tables in glm_fast/iq_kernels, multi-argument kernel names. Idempotent."""
import re, sys, pathlib
root = pathlib.Path(sys.argv[1]).resolve()
changed = 0
def edit(rel, fn):
    global changed
    p = root / rel
    s = p.read_text(encoding="utf-8", errors="surrogateescape"); t = fn(s)
    if t != s:
        p.write_text(t, encoding="utf-8", errors="surrogateescape"); changed += 1; print("  fixed", rel)

# kernel names dpct could not deduce (dpct_placeholder): unnamed lambdas are fine in SYCL 2020
for p in (root / "src").rglob("*.cpp"):
    edit(str(p.relative_to(root)), lambda s: re.sub(r"parallel_for<\s*dpct_kernel_name<.*?>>\(", "parallel_for(", s, flags=re.S))

# Strata fixups 8b/8d, applied to glm_fast too: with GGML_COMMON_IMPL_SYCL the tables are plain static const
# arrays usable from device code, so drop the parameters/arguments/captures dpct threaded them through.
TABLES = r"(iq2xxs_grid|iq2xs_grid|iq2s_grid|iq3xxs_grid|iq3s_grid|iq1s_grid_gpu|kmask_iq2xs|ksigns_iq2xs|ksigns64|kvalues_iq4nl)"
def untangle(s):
    s = re.sub(r"\b" + TABLES + r"\.get_ptr\(\)", r"\1", s)
    s = re.sub(r"^\s*" + TABLES + r"\.init\([^;]*\);\n", "", s, flags=re.M)
    s = re.sub(r"^\s*auto \w+_ptr_ct\d+ = \w+;\n", "", s, flags=re.M)
    s = re.sub(r",\s*(const )?(uint64_t|uint32_t|uint8_t|int8_t) \*" + TABLES + r"\b(?!\s*\[)", "", s)
    s = re.sub(r"\(\s*(const )?(uint64_t|uint32_t|uint8_t|int8_t) \*" + TABLES + r"\s*\)", "()", s)
    s = re.sub(r",\s*" + TABLES + r"(_ptr_ct\d+)?\b(?![\[\w(.])", "", s)
    s = re.sub(r"\(\s*" + TABLES + r"(_ptr_ct\d+)?\s*\)(?![\[\w])", "()", s)
    return s
# glm_fast: tools/untangle_fast.py (macro-aware) does this - running it here strips the GLMF_IQ_F table argument
print(changed, "files changed")
