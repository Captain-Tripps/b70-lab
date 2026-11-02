"""Maya GLM port, round 19: the route kernel stops copying the FFN input (16 KB) into the host request ring when no
host work can read it.  ROUTE_FAST wrote rq->x at the kernel's start on every route; the host reads it only for a
request with cpu_mask != 0, and cpu_mask bits come only from the CPU lane (cpu_plan != 0) or helper-owned experts
(d.helper_owned != null).  The route's final system fence waited for those writes to drain over PCIe: ~100 us of
the ~120 us route (fixups18's profile, all experts in VRAM, CPU lane off).  Now: the early copy only when the CPU
lane or a helper is configured; otherwise the copy after the plan when the route did give the host work (the
non-fast path's rule) - the host sees x in every request it reads.  Backups in <raw>/../pre-fix19/.  Idempotent."""
import sys, pathlib, shutil
raw = pathlib.Path(sys.argv[1]); bk = raw.parent / "pre-fix19"; bk.mkdir(exist_ok=True)
p = raw / "src/kernels/cuda/glm_fast.dp.cpp"
s = p.read_text(encoding="utf-8", errors="surrogateescape")
subs = [
    ("""    if (a.fast) {
        MoeRequest* rq0 = (MoeRequest*) a.d.ring + ((*a.d.seq + 1) % kRingSize);""",
     """    // SYCL port (fixups19): only when the host may read it (the CPU lane or a helper); else after the plan below
    const bool x_early = a.fast && (a.cpu_plan != 0ull || a.d.helper_owned != nullptr);
    if (x_early) {
        MoeRequest* rq0 = (MoeRequest*) a.d.ring + ((*a.d.seq + 1) % kRingSize);""", 1),
    ("""    if (s_cpu != 0u && !a.fast)
#pragma unroll
        for (int e = tid; e < a.n_embd; e += ROUTE_THREADS) rq->x[e] = a.x[e];""",
     """    if (s_cpu != 0u && !x_early)   // SYCL port (fixups19): was !a.fast
#pragma unroll
        for (int e = tid; e < a.n_embd; e += ROUTE_THREADS) rq->x[e] = a.x[e];""", 1),
]
if "fixups19" not in s:
    shutil.copy(p, bk / "glm_fast.dp.cpp")
    for old, new, n in subs:
        assert s.count(old) == n, (old[:60], s.count(old)); s = s.replace(old, new)
    p.write_text(s, encoding="utf-8", errors="surrogateescape"); print("  route x copy gated")
else: print("  already")
