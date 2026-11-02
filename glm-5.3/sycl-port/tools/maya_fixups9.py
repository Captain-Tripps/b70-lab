#!/usr/bin/env python3
"""Maya GLM port, round 9: the GPU never sees a host store to host memory while its kernel runs, and a no-op kernel
cannot help once the wait grid holds every core (spin2/spin3.cpp, 2026-10-31). A copy-engine memcpy into DEVICE memory
is seen at once even then. So the routing answer (MoeResponse) gets a device mirror: the kernels read md.resp = the
mirror, the service still fills resp_h and publishes it - payload first, seq word last (in-order side queue) - and
each streamed ready word is published under a lock (a stale copy landing late could clear a bit). Needs fixups8.
Idempotent."""
import re, sys, pathlib
root = pathlib.Path(sys.argv[1]).resolve()
p = root / "src/core/glm_fast_path.dp.cpp"
s = p.read_text(encoding="utf-8", errors="surrogateescape")
if "sycl_publish_resp" not in s:
    helper = '''
// SYCL port (fixups9): the host's routing answer reaches a running kernel only through device memory written by the
// copy engine - publish resp_h into the device mirror md.resp: everything after seq first, then seq (in-order queue)
static inline sycl::queue& sycl_side_queue(dpct::queue_ptr cs) {
    thread_local sycl::queue* k = nullptr;
    thread_local dpct::queue_ptr k_for = nullptr;
    if (k == nullptr || k_for != cs) {
        k = new sycl::queue(cs->get_context(), cs->get_device(), sycl::property::queue::in_order());
        k_for = cs;
    }
    return *k;
}
static inline void sycl_publish_resp(dpct::queue_ptr cs, void* resp_d, const void* resp_h, size_t bytes) {
    sycl::queue& k = sycl_side_queue(cs);
    std::atomic_thread_fence(std::memory_order_seq_cst);
    k.memcpy((char*) resp_d + sizeof(unsigned int), (const char*) resp_h + sizeof(unsigned int), bytes - sizeof(unsigned int));
    k.memcpy(resp_d, resp_h, sizeof(unsigned int)).wait();
}
static inline void sycl_publish_word(dpct::queue_ptr cs, void* dst_d, const unsigned int* src_h) {
    static std::mutex mu;   // serialised: each copy carries every bit set so far, and lands after the one before
    std::lock_guard<std::mutex> lk(mu);
    sycl_side_queue(cs).memcpy(dst_d, (const void*) src_h, sizeof(unsigned int)).wait();
}
'''
    i = s.index("static inline void sycl_host_kick(")
    s = s[:i] + helper.lstrip("\n") + "\n" + s[i:]
    # the mirror
    a = "    F->resp_h = (gf::MoeResponse*) hp;\n    dp = (void *)hp;\n    F->md.resp = dp;\n"
    assert s.count(a) == 1, "resp alloc"
    s = s.replace(a, a +
        "    // SYCL port (fixups9): the kernels read a device mirror of the answer (sycl_publish_resp)\n"
        "    void* resp_m = sycl::malloc_device(sizeof(gf::MoeResponse), dpct::get_in_order_queue());   // (md.resp is const void*)\n"
        "    if (resp_m == nullptr) { err = \"glm fast: the routing response mirror did not allocate\"; return false; }\n"
        "    dpct::get_in_order_queue().memset(resp_m, 0, sizeof(gf::MoeResponse)).wait();\n"
        "    F->md.resp = resp_m;\n")
    n1 = s.count("Rp->seq = next; sycl_host_kick(fast_->cs);")
    s = s.replace("Rp->seq = next; sycl_host_kick(fast_->cs);",
                  "Rp->seq = next; sycl_publish_resp(fast_->cs, const_cast<void*>(F->md.resp), Rp, sizeof(gf::MoeResponse));")
    n2 = s.count("->fetch_or(1u << part, std::memory_order_release); sycl_host_kick(fast_->cs);")
    s = s.replace("->fetch_or(1u << part, std::memory_order_release); sycl_host_kick(fast_->cs);",
                  "->fetch_or(1u << part, std::memory_order_release);\n"
                  "                        sycl_publish_word(fast_->cs, (char*) const_cast<void*>(F->md.resp) + offsetof(gf::MoeResponse, ready) +\n"
                  "                                          sizeof(unsigned int) * (size_t) mi[m], (const unsigned int*) &Rp->ready[mi[m]]);")
    print(f"  glm_fast_path.dp.cpp: mirror + {n1} answer publish(es) (want 2) + {n2} ready publish(es) (want 1)")
    if "#include <mutex>" not in s:
        s = s.replace("#include <algorithm>\n", "#include <algorithm>\n#include <mutex>\n", 1)
else:
    print("  already applied")
p.write_text(s, encoding="utf-8", errors="surrogateescape")
