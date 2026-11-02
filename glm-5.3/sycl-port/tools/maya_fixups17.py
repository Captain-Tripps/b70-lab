"""Maya GLM port, round 17: the three cross-card hops queue the next card's work at once, behind a host task that
waits for the previous card's hop event (fixups13 made the main thread wait there - the next card then idled while
the host submitted its ~12 layers one kernel at a time, ~2 ms a hop).  MAYA_HOP_HOSTWAIT=1: the old blocking wait.
Backups in <raw>/../pre-fix17/.  Idempotent."""
import sys, pathlib, shutil
raw = pathlib.Path(sys.argv[1]); bk = raw.parent / "pre-fix17"; bk.mkdir(exist_ok=True)
HELPER = '''
// SYCL port (fixups17): queue q's later work behind another device's event without blocking the calling thread - a
// host task on q waits for it (a cross-device barrier aborts in UR on Windows L0).  MAYA_HOP_HOSTWAIT=1: block here.
inline void maya_queue_wait(sycl::queue* q, sycl::event* ev) {
    static const bool block = std::getenv("MAYA_HOP_HOSTWAIT") != nullptr;
    if (block) { ev->wait(); return; }
    sycl::event e = *ev;
    q->submit([&](sycl::handler& h) { h.host_task([e]() mutable { e.wait(); }); });
}
'''
c = raw / "include/maya_compat.hpp"
s = c.read_text(encoding="utf-8")
if "maya_queue_wait" not in s:
    shutil.copy(c, bk / "maya_compat.hpp")
    if "#include <cstdlib>" not in s: s = s.replace("#pragma once", "#pragma once\n#include <cstdlib>", 1)
    c.write_text(s + HELPER, encoding="utf-8"); print("  helper added")
p = raw / "src/core/glm_fast_path.dp.cpp"
s = p.read_text(encoding="utf-8", errors="surrogateescape")
T = " // SYCL port (fixups13): cross-device barrier aborts on Windows L0 - host wait"
subs = [("(FA->ev_hop)->wait();" + T, "maya_queue_wait(FB->cs, FA->ev_hop);   // SYCL port (fixups17): no host block at the hop", 2),
        ("(head->spec_ev_hop_[sl])->wait();" + T, "maya_queue_wait(F->cs, head->spec_ev_hop_[sl]);   // SYCL port (fixups17)", 1)]
if "fixups17" not in s:
    shutil.copy(p, bk / "glm_fast_path.dp.cpp")
    for old, new, n in subs:
        assert s.count(old) == n, (old, s.count(old)); s = s.replace(old, new)
    p.write_text(s, encoding="utf-8", errors="surrogateescape"); print("  3 hops")
else: print("  already")
