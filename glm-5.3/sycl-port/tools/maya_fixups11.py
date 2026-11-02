#!/usr/bin/env python3
"""Maya GLM port, round 11: the token readbacks (device int -> malloc_host int) become one-thread kernels.
On B70/Windows/L0 a USM host<->device copy queued behind a RUNNING kernel blocks every other host<->device copy in the
context until that kernel ends (spin4.cpp modes 3/7/8, copy engine on or off).  The token's readback sat behind the MoE
wait kernel, so the service's answer copy (fixups9) never landed: the async decode deadlocked.  Idempotent."""
import re, sys, pathlib
p = pathlib.Path(sys.argv[1]).resolve() / "src/core/glm_fast_path.dp.cpp"
s = p.read_text(encoding="utf-8", errors="surrogateescape")
TAG = "// SYCL port: kernel, not a host copy (fixups11)"
pat = re.compile(r"(?P<q>[\w>-]+?)->memcpy\((?P<dst>[^,;]*tok_h[^,;]*), (?P<src>[^,;]+), sizeof\(int\)\);(?!\s*// SYCL port: kernel)")
n = 0
def repl(m):
    global n; n += 1
    return ("{ int* h_ = " + m["dst"] + "; const int* d_ = " + m["src"] + "; " + m["q"] +
            "->single_task([=] { *h_ = *d_; }); } " + TAG)
t = pat.sub(repl, s)
print(f"  token readbacks: {n} site(s)")
if t != s: p.write_text(t, encoding="utf-8", errors="surrogateescape")
