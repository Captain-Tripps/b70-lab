#!/usr/bin/env python3
"""Maya GLM port, round 7: device spin-waits read their flag through a plain `volatile` load. CUDA keeps those coherent;
on Intel Xe a volatile load can be served from the non-coherent per-core L1, so a grid barrier (hc2) or a MoE wait on
the host's answer never sees the store and the token hangs (layer 0, GPU idle-looking). Use atomic loads: device
scope for the grid-barrier counter, system scope for host-memory sequence words. Idempotent."""
import re, sys, pathlib
root = pathlib.Path(sys.argv[1]).resolve()
TAG = "/* SYCL: atomic load, not volatile */"
p = root / "src/kernels/cuda/glm_fast.dp.cpp"
s = p.read_text(encoding="utf-8", errors="surrogateescape")
n0 = s.count(TAG)
# 1. the grid barrier's counter
s = s.replace("while (*(volatile unsigned long long*) ctr < target) {",
              "while (" + TAG + " sycl::atomic_ref<unsigned long long, sycl::memory_order::relaxed, sycl::memory_scope::device, "
              "sycl::access::address_space::generic_space>(*ctr).load() < target) {")
# 2. host-answer sequence words: while (r->seq != s_need) / while (a->seq != s_need) / ((volatile const MoeResponse*) r)->seq
def seq_load(ptr):
    return (TAG + " sycl::atomic_ref<unsigned int, sycl::memory_order::relaxed, sycl::memory_scope::system, "
            "sycl::access::address_space::generic_space>(*(unsigned int*) &(" + ptr + ")->seq).load()")
s = re.sub(r"while \(\(\(volatile const MoeResponse\*\) (\w+)\)->seq != s_need\)", lambda m: "while (" + seq_load(m.group(1)) + " != s_need)", s)
s = re.sub(r"while \((\w+)->seq != s_need\)", lambda m: "while (" + seq_load(m.group(1)) + " != s_need)", s)
# 3. a device word another kernel's thread changes: while (*(volatile unsigned int*) d.wait_seq == s_need)
s = re.sub(r"while \(\*\(volatile unsigned int\*\) ([\w.]+) == (\w+)\)",
           lambda m: "while (" + TAG + " sycl::atomic_ref<unsigned int, sycl::memory_order::relaxed, sycl::memory_scope::device, "
                     "sycl::access::address_space::generic_space>(*(unsigned int*) " + m.group(1) + ").load() == " + m.group(2) + ")", s)
# 4. the streamed fetch's per-chunk ready bits (host memory)
s = s.replace("while (((r->ready[i] >> bit) & 1u) == 0u) {",
              "while (((" + TAG + " sycl::atomic_ref<unsigned int, sycl::memory_order::relaxed, sycl::memory_scope::system, "
              "sycl::access::address_space::generic_space>(*(unsigned int*) &r->ready[i]).load() >> bit) & 1u) == 0u) {")
# 5. the store that releases those spinners (block 0 clears wait_seq): atomic too, so it reaches L3
s = s.replace("if (tid == 0) *(volatile unsigned int*) d.wait_seq = 0u;",
              "if (tid == 0) " + TAG + " sycl::atomic_ref<unsigned int, sycl::memory_order::relaxed, sycl::memory_scope::device, "
              "sycl::access::address_space::generic_space>(*(unsigned int*) d.wait_seq).store(0u);")
print(f"  glm_fast.dp.cpp: {s.count(TAG) - n0} site(s) patched (want 9)")
p.write_text(s, encoding="utf-8", errors="surrogateescape")
