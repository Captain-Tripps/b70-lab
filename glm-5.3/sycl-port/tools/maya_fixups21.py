"""Maya GLM port, round 21: the cross-card hop goes back to the main thread's blocking wait BY DEFAULT.  fixups17/20's
overlapped hop (a host task orders the next card) is ~25-35% faster with MTP but hangs: long runs (768 tokens) hung
2 of 2 with the blocking host task and 1 of 3 with the polling one (cause not found yet; likely the B70/L0 copy-
behind-a-spinning-kernel stall of fixups11/12).  MAYA_HOP_ASYNC=1 opts in to the polling host task (fixups20),
MAYA_HOP_BLOCKWAIT=1 with it to fixups17's blocking host task.  Backups in <raw>/../pre-fix21/.  Idempotent."""
import sys, pathlib, shutil
raw = pathlib.Path(sys.argv[1]); bk = raw.parent / "pre-fix21"; bk.mkdir(exist_ok=True)
c = raw / "include/maya_compat.hpp"
s = c.read_text(encoding="utf-8")
old = '    static const bool block = std::getenv("MAYA_HOP_HOSTWAIT") != nullptr;'
new = ('    // SYCL port (fixups21): blocking by default - the overlapped hop hangs on long runs (MAYA_HOP_ASYNC=1: opt in)\n'
       '    static const bool block = std::getenv("MAYA_HOP_ASYNC") == nullptr;')
if "fixups21" not in s:
    assert s.count(old) == 1, s.count(old)
    shutil.copy(c, bk / "maya_compat.hpp")
    c.write_text(s.replace(old, new), encoding="utf-8"); print("  hop blocks by default")
else: print("  already")
