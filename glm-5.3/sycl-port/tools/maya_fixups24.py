"""Maya GLM port, round 24: the overlapped cross-card hop is back ON by default, on SYCL's Level Zero v1 adapter.
Root cause of the MTP hangs (cdb stacks of a hung run, 2026-11-01): with the hop's host task in a queue, the SYCL
runtime enqueues the kernels behind it from its own worker thread, so two threads append kernels to the driver at
once (main thread: sycl::submit_kernel_direct -> urEnqueueKernelLaunchWithArgsExp; SYCL worker: the same) and,
together with a driver-internal thread, they deadlock on SRW locks inside ze_intel_gpu64 - only in the v2 adapter
(ur_adapter_level_zero_v2).  On the v1 adapter (SYCL_UR_USE_LEVEL_ZERO_V2=0) 16 of 16 768-token MTP runs were clean.
So: generate sets SYCL_UR_USE_LEVEL_ZERO_V2=0 before SYCL starts unless the caller set it; the hop overlaps when the
v1 adapter is in use (MAYA_HOP_SYNC=1: the blocking hop), and on v2 only with MAYA_HOP_ASYNC=1 as before.
Backups in <raw>/../pre-fix24/.  Idempotent."""
import sys, pathlib, shutil
raw = pathlib.Path(sys.argv[1]); bk = raw.parent / "pre-fix24"; bk.mkdir(exist_ok=True)
c = raw / "include/maya_compat.hpp"
s = c.read_text(encoding="utf-8")
old = """    // SYCL port (fixups21): blocking by default - the overlapped hop hangs on long runs (MAYA_HOP_ASYNC=1: opt in)
    static const bool block = std::getenv("MAYA_HOP_ASYNC") == nullptr;"""
new = """    // SYCL port (fixups24): overlapped on the L0 v1 adapter (the v2 adapter deadlocks in the driver when the SYCL
    // worker thread and this thread launch kernels at once); MAYA_HOP_SYNC=1 blocks, MAYA_HOP_ASYNC=1 forces overlap
    static const bool block = [] {
        const char* v2 = std::getenv("SYCL_UR_USE_LEVEL_ZERO_V2");
        const bool v1 = v2 != nullptr && v2[0] == '0';
        const bool b = std::getenv("MAYA_HOP_SYNC") != nullptr || (!v1 && std::getenv("MAYA_HOP_ASYNC") == nullptr);
        std::fprintf(stderr, "glm hop: %s (L0 adapter %s)\\n", b ? "blocking" : "overlapped", v1 ? "v1" : "v2");
        return b;
    }();"""
if "fixups24" not in s:
    assert s.count(old) == 1, s.count(old)
    shutil.copy(c, bk / "maya_compat.hpp")
    s = s.replace(old, new)
    if "#include <cstdio>" not in s: s = s.replace("#pragma once", "#pragma once\n#include <cstdio>", 1)
    c.write_text(s, encoding="utf-8"); print("  hop default: overlapped on v1")
p = raw / "src/core/glm_fast_path.dp.cpp"
t = p.read_text(encoding="utf-8", errors="surrogateescape")
anchor = "namespace strata::core {\n"
init = anchor + """
// SYCL port (fixups24): the Level Zero v1 adapter unless the caller chose (set before main, so before SYCL reads it):
// the v2 adapter deadlocks in the driver under the overlapped cross-card hop (see maya_queue_wait)
static const int maya_l0_v1_init = [] {
    if (std::getenv("SYCL_UR_USE_LEVEL_ZERO_V2") == nullptr) {
#ifdef _WIN32
        _putenv_s("SYCL_UR_USE_LEVEL_ZERO_V2", "0");
#else
        setenv("SYCL_UR_USE_LEVEL_ZERO_V2", "0", 0);
#endif
    }
    return 0;
}();
"""
if "maya_l0_v1_init" not in t:
    assert t.count(anchor) >= 1
    shutil.copy(p, bk / "glm_fast_path.dp.cpp")
    p.write_text(t.replace(anchor, init, 1), encoding="utf-8", errors="surrogateescape"); print("  v1 adapter default")
else: print("  already")
