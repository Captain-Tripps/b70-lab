#!/usr/bin/env python3
"""Maya GLM port, round 6: cudaFreeHost came through dpct as a bare CRT free() in three places - on sycl::malloc_host
memory that corrupts the Windows heap (0xC0000374 right after the RAM tier pinned). Use sycl::free. Also: dpct's
device.hpp gated the free-memory query on __SYCL_COMPILER_VERSION, which icpx 2026 no longer defines (get_memory_info
always said 0 free). Idempotent."""
import re, sys, pathlib
root = pathlib.Path(sys.argv[1]).resolve()
Q = "sycl::free({}, dpct::get_in_order_queue()); // SYCL port: was cudaFreeHost (dpct emitted a CRT free)"
def patch(rel, pat, var, want):
    p = root / rel
    s = p.read_text(encoding="utf-8", errors="surrogateescape")
    t, n = re.subn(pat, lambda m: m.group(1) + Q.format(var), s)
    print(f"  {rel}: {n} site(s) (want {want})")
    if t != s: p.write_text(t, encoding="utf-8", errors="surrogateescape")
patch("src/core/glm_fast_path.dp.cpp", r"(static void pin_free\(void\* p, size_t bytes\) \{\s*)free\(p\);", "p", 1)
patch("src/program/generate.cpp", r"(\n[ \t]*)free\(h\);", "h", 2)
d = root / "include/dpct/device.hpp"
s = d.read_text(encoding="utf-8", errors="surrogateescape")
t = s.replace("#if (defined(__SYCL_COMPILER_VERSION) && __SYCL_COMPILER_VERSION >= 20221105)\r\n    if (!has(sycl::aspect::ext_intel_free_memory))",
              "#if 1 // SYCL port: icpx 2026 no longer defines __SYCL_COMPILER_VERSION\r\n    if (!has(sycl::aspect::ext_intel_free_memory))", 1)
print("  device.hpp guard:", "patched" if t != s else "already / not found")
if t != s: d.write_text(t, encoding="utf-8", errors="surrogateescape")
