#!/usr/bin/env python3
"""Maya GLM port, round 8: on a B70 under Windows (Level Zero), a running kernel never sees a host thread's store to
sycl::malloc_host (or shared) memory - not with volatile, atomic, or acquire loads (spin2.cpp, 2026-10-31). Any
submission on a second queue after the store makes it visible at once. The fast path's GPU spins on host answers
(MoeResponse seq / ready bits, CpuAnswer seq), so every such host write is followed by sycl_host_kick(): a no-op
kernel on a per-thread side queue in the compute queue's context. MAYA_SYCL_KICK=0 turns it off. Idempotent."""
import re, sys, pathlib
root = pathlib.Path(sys.argv[1]).resolve()
p = root / "src/core/glm_fast_path.dp.cpp"
s = p.read_text(encoding="utf-8", errors="surrogateescape")
TAG = "sycl_host_kick(fast_->cs);"
if "static inline void sycl_host_kick" not in s:
    helper = '''
// SYCL port: a host store to host-mapped memory reaches a RUNNING kernel only once something else is submitted to the
// device (B70, Windows, Level Zero: spin2.cpp) - so each host answer the GPU spins on is followed by a no-op kernel on a
// side queue of this thread's own. MAYA_SYCL_KICK=0 turns it off.
static inline void sycl_host_kick(dpct::queue_ptr cs) {
    static const bool on = [] { const char* v = getenv("MAYA_SYCL_KICK"); return v == nullptr || std::atoi(v) != 0; }();
    if (!on || cs == nullptr) return;
    thread_local sycl::queue* k = nullptr;
    thread_local dpct::queue_ptr k_for = nullptr;
    if (k == nullptr || k_for != cs) {
        k = new sycl::queue(cs->get_context(), cs->get_device(), sycl::property::queue::in_order());
        k_for = cs;
    }
    k->single_task([] {});   // (no wait: a spinning grid can hold every core, and the submission is what publishes)
}
'''
    i = s.index('#include "ggml.h"\n') + len('#include "ggml.h"\n')
    s = s[:i] + helper + s[i:]
n0 = s.count(TAG)
pats = [r"(    for \(int j = 0; j < nb; \+\+j\) ans\[j\]->seq = seq\[j\];)",
        r"(\n[ \t]*j\.ans->seq = j\.seq;)",
        r"(\n[ \t]*Rp->seq = next;)",
        r"(\n[ \t]*ans->seq = next;)",
        r"(->fetch_or\(1u << part, std::memory_order_release\);)"]
for pat in pats:
    s = re.sub(pat + r"(?! " + re.escape(TAG) + ")", lambda m: m.group(1) + " " + TAG, s)
print(f"  glm_fast_path.dp.cpp: {s.count(TAG) - n0} kick(s) added (want 7)")
p.write_text(s, encoding="utf-8", errors="surrogateescape")
