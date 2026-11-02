"""Maya GLM port, round 26: the MTP step queues the tail group and the head group from two threads at once.
After fixups25 the host's kernel submission is the long pole (a step = ~713 launches: enqueue tail ~7 ms + enqueue
head ~9 ms back to back on one thread).  The two touch disjoint cards and state: spec_tail(q+2) waits on the head's
hop slot (q+2)&1 on the device, spec_head(q+3) + kda_all write only head-group models and slot (q+3)&1, whose reader
(the tail's q+1 pass) is already done (take() returned its token).  dpct's current device is thread_local.  So the tail
goes to a std::async thread while this thread does kda_all + spec_head, joined before the next step.
On by default; MAYA_SPEC_PAR=0: serial as before.  Backups in <raw>/../pre-fix26/.  Idempotent."""
import sys, pathlib, shutil
raw = pathlib.Path(sys.argv[1]); bk = raw.parent / "pre-fix26"; bk.mkdir(exist_ok=True)
p = raw / "src/core/glm_fast_path.dp.cpp"
t = p.read_text(encoding="utf-8", errors="surrogateescape")
old = """        if (!B->spec_tail(hl, q + 2, err)) { ok = false; break; }
        lap(3);
        kda_all(false);
        if (cancel) fast_->spec_cancellable = true;   // q+3 with the new draft: speculative
        if (!spec_head(q + 3, d2, err)) { ok = false; break; }
        lap(4);"""
new = """        // SYCL port (fixups26): the tail queues from a second thread while this one queues the head
        static const bool spec_par = [] {
            const char* e = std::getenv("MAYA_SPEC_PAR");
            const bool on = e == nullptr || e[0] != '0';   // default on (8/8 long runs clean)
            std::fprintf(stderr, "glm spec: tail/head enqueue %s\\n", on ? "on two threads" : "serial");
            return on;
        }();
        if (spec_par) {
            std::string terr;
            auto tail = std::async(std::launch::async, [&] { return B->spec_tail(hl, q + 2, terr); });
            kda_all(false);
            if (cancel) fast_->spec_cancellable = true;   // q+3 with the new draft: speculative
            const bool hok = spec_head(q + 3, d2, err);
            const bool tok = tail.get();
            if (!tok) err = terr;
            if (!tok || !hok) { ok = false; break; }
            lap(3);
            lap(4);
        } else {
        if (!B->spec_tail(hl, q + 2, err)) { ok = false; break; }
        lap(3);
        kda_all(false);
        if (cancel) fast_->spec_cancellable = true;   // q+3 with the new draft: speculative
        if (!spec_head(q + 3, d2, err)) { ok = false; break; }
        lap(4);
        }"""
if "fixups26" not in t:
    assert t.count(old) == 1, t.count(old)
    shutil.copy(p, bk / "glm_fast_path.dp.cpp")
    t = t.replace(old, new)
    if "#include <future>" not in t: t = t.replace("#include <functional>\n", "#include <functional>\n#include <future>\n", 1)
    p.write_text(t, encoding="utf-8", errors="surrogateescape"); print("  spec tail/head on two threads (MAYA_SPEC_PAR)")
else: print("  already")
