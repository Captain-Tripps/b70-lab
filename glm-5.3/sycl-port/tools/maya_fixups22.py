"""Maya GLM port, round 22 (diagnosis): the MTP head->tail hop (spec_ev_hop_) gets its own switch so the two hop kinds
can be tested apart.  The overlapped hop never hung without MTP (4/4 768-token runs) - only with it.
MAYA_HOP_ASYNC=1: the card-to-card hops overlap (as before); MAYA_HOP_SPEC_ASYNC=1 / =0 overrides the head->tail hop
(default: follows MAYA_HOP_ASYNC).  Backups in <raw>/../pre-fix22/.  Idempotent."""
import sys, pathlib, shutil
raw = pathlib.Path(sys.argv[1]); bk = raw.parent / "pre-fix22"; bk.mkdir(exist_ok=True)
c = raw / "include/maya_compat.hpp"
s = c.read_text(encoding="utf-8")
old_sig = "inline void maya_queue_wait(sycl::queue* q, sycl::event* ev) {"
old_blk = '    static const bool block = std::getenv("MAYA_HOP_ASYNC") == nullptr;\n    if (block) { ev->wait(); return; }'
new_sig = "inline void maya_queue_wait(sycl::queue* q, sycl::event* ev, bool spec = false) {"
new_blk = ('    static const bool block = std::getenv("MAYA_HOP_ASYNC") == nullptr;\n'
           '    // SYCL port (fixups22): the MTP head->tail hop on its own switch (MAYA_HOP_SPEC_ASYNC=0/1; default as above)\n'
           '    static const int spec_sw = std::getenv("MAYA_HOP_SPEC_ASYNC") ? std::atoi(std::getenv("MAYA_HOP_SPEC_ASYNC")) : -1;\n'
           '    if (spec ? (spec_sw < 0 ? block : spec_sw == 0) : block) { ev->wait(); return; }')
if "fixups22" not in s:
    assert s.count(old_sig) == 1 and s.count(old_blk) == 1, (s.count(old_sig), s.count(old_blk))
    shutil.copy(c, bk / "maya_compat.hpp")
    c.write_text(s.replace(old_sig, new_sig).replace(old_blk, new_blk), encoding="utf-8"); print("  switch added")
p = raw / "src/core/glm_fast_path.dp.cpp"
t = p.read_text(encoding="utf-8", errors="surrogateescape")
o = "maya_queue_wait(F->cs, head->spec_ev_hop_[sl]);"
if "spec_ev_hop_[sl], true)" not in t:
    assert t.count(o) == 1, t.count(o)
    shutil.copy(p, bk / "glm_fast_path.dp.cpp")
    p.write_text(t.replace(o, "maya_queue_wait(F->cs, head->spec_ev_hop_[sl], true);"), encoding="utf-8", errors="surrogateescape")
    print("  spec hop tagged")
else: print("  already")
