"""Maya GLM port, round 25: the overlapped cross-card hop as a DEVICE-side wait.  fixups17's host task did not
overlap anything on the host: with a host task pending in an in-order queue, every later submit to that queue blocks
the submitting thread until the host task ends (bench_hop2, card A busy: 280-950 us per kernel submit behind a host
task vs ~18 us behind a barrier) - so the main thread sat out card A's whole pass before it could queue card B's
layers.  The shared Windows context (strata_device_context) lets q->ext_oneapi_submit_barrier({A's event}) wait on
the other card's event in the driver; on the L0 v1 adapter it works (it aborted in UR when fixups17 tried it, then on
v2).  MAYA_HOP_HOSTTASK=1: fixups20's polling host task again.  Backups in <raw>/../pre-fix25/.  Idempotent."""
import sys, pathlib, shutil
raw = pathlib.Path(sys.argv[1]); bk = raw.parent / "pre-fix25"; bk.mkdir(exist_ok=True)
c = raw / "include/maya_compat.hpp"
s = c.read_text(encoding="utf-8")
old = """    sycl::event e = *ev;
    // SYCL port (fixups20): poll the status"""
new = """    // SYCL port (fixups25): a device-side wait - a host task blocks every later submit to q until it ends
    static const bool host_task = std::getenv("MAYA_HOP_HOSTTASK") != nullptr;
    if (!host_task) { q->ext_oneapi_submit_barrier({*ev}); return; }
    sycl::event e = *ev;
    // SYCL port (fixups20): poll the status"""
if "fixups25" not in s:
    assert s.count(old) == 1, s.count(old)
    shutil.copy(c, bk / "maya_compat.hpp")
    c.write_text(s.replace(old, new), encoding="utf-8"); print("  hop: device-side barrier")
else: print("  already")
