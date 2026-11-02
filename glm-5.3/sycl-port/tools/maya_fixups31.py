"""Maya GLM port, round 31: dpct's device_ext::destroy_queue never destroys the device's own default queues.
SYCLomatic maps CUDA's default stream (0 - never destroyed) to &dpct::get_in_order_queue(); members that default to
it (Glm5Model::hh_s_, PrefillState::xs / kv_ss, ...) were destroyed at teardown, and every later free / wait on the
default queue crashed (exit access violation / fail-fast after a prompt, 2026-11-01).  Backups in <raw>/../pre-fix31/."""
import sys, pathlib, shutil
raw = pathlib.Path(sys.argv[1]); bk = raw.parent / "pre-fix31"; bk.mkdir(exist_ok=True)
p = raw / "include/dpct/device.hpp"
t = p.read_text(encoding="utf-8", errors="surrogateescape")
old = """  void destroy_queue(sycl::queue *&queue) {
    std::lock_guard<mutex_type> lock(m_mutex);
"""
new = """  void destroy_queue(sycl::queue *&queue) {
    std::lock_guard<mutex_type> lock(m_mutex);
    // SYCL port (fixups31): the default queues stand for CUDA's stream 0 - never destroyed
    if (queue == _q_in_order || queue == _q_out_of_order) { queue = nullptr; return; }
"""
if "fixups31" not in t:
    assert t.count(old) == 1, t.count(old)
    shutil.copy(p, bk / "device.hpp")
    p.write_text(t.replace(old, new), encoding="utf-8", errors="surrogateescape"); print("  dpct destroy_queue keeps the default queues")
else: print("  already")
