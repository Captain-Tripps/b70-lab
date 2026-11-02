"""Maya GLM port, round 30: the access violation at exit.  ~Glm5Model destroyed hh_s_ (the head split's stream), whose
SYCL default is the device's own in-order queue (CUDA's is stream 0, never destroyed) - every later
sycl::free(.., dpct::get_in_order_queue()) in the destructor then ran on a dead queue and crashed in
queue::get_context (cdb + link map, 2026-11-01).  Destroy hh_s_ only when the model created it.
Backups in <raw>/../pre-fix30/.  Idempotent."""
import sys, pathlib, shutil
raw = pathlib.Path(sys.argv[1]); bk = raw.parent / "pre-fix30"; bk.mkdir(exist_ok=True)
p = raw / "src/core/glm_model.dp.cpp"
t = p.read_text(encoding="utf-8", errors="surrogateescape")
old = "    if (hh_s_) dpct::get_current_device().destroy_queue(hh_s_);"
new = ("    // SYCL port (fixups30): hh_s_ defaults to the device's own in-order queue - destroying it crashed every free below\n"
       "    if (hh_s_ && hh_s_ != &dpct::get_in_order_queue()) dpct::get_current_device().destroy_queue(hh_s_);")
if "fixups30" not in t:
    assert t.count(old) == 1, t.count(old)
    shutil.copy(p, bk / "glm_model.dp.cpp")
    p.write_text(t.replace(old, new), encoding="utf-8", errors="surrogateescape"); print("  hh_s_: destroy only an owned queue")
else: print("  already")
