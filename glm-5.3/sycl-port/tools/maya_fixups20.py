"""Maya GLM port, round 20: fixups17's hop host task blocked in event::wait() (zeEventHostSynchronize) while the main
thread kept submitting to the other cards - long runs hung (2 of 2 at 768 tokens after fixups19; a bigger host-task
pool, SYCL_QUEUE_THREAD_POOL_SIZE=8, hung within ~100 tokens: the L0 multi-thread wait deadlock, not pool starvation).
Now the host task polls the event's execution status with a yield instead of the driver's blocking wait.
MAYA_HOP_HOSTWAIT=1 keeps the old blocking wait on the main thread (safe fallback); MAYA_HOP_BLOCKWAIT=1 is fixups17's
blocking host task (A/B).  Backups in <raw>/../pre-fix20/.  Idempotent."""
import sys, pathlib, shutil
raw = pathlib.Path(sys.argv[1]); bk = raw.parent / "pre-fix20"; bk.mkdir(exist_ok=True)
c = raw / "include/maya_compat.hpp"
s = c.read_text(encoding="utf-8")
old = """    sycl::event e = *ev;
    q->submit([&](sycl::handler& h) { h.host_task([e]() mutable { e.wait(); }); });
}"""
new = """    sycl::event e = *ev;
    // SYCL port (fixups20): poll the status - a blocking wait here deadlocked L0 against the submitting thread
    static const bool block_task = std::getenv("MAYA_HOP_BLOCKWAIT") != nullptr;
    if (block_task) { q->submit([&](sycl::handler& h) { h.host_task([e]() mutable { e.wait(); }); }); return; }
    q->submit([&](sycl::handler& h) {
        h.host_task([e]() {
            while (e.get_info<sycl::info::event::command_execution_status>() !=
                   sycl::info::event_command_status::complete) std::this_thread::yield();
        });
    });
}"""
if "fixups20" not in s:
    assert s.count(old) == 1, s.count(old)
    shutil.copy(c, bk / "maya_compat.hpp")
    s = s.replace(old, new)
    if "#include <thread>" not in s: s = s.replace("#pragma once", "#pragma once\n#include <thread>", 1)
    c.write_text(s, encoding="utf-8"); print("  hop host task polls")
else: print("  already")
