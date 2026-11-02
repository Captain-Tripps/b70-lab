"""Maya GLM port, round 23: the card-to-card hop buffer (FastState::hop_h, pinned, hc x n_embd) becomes a ring of 4
slots by position for hop_to_next (the spec path's card hops).  With the overlapped hop (MAYA_HOP_ASYNC=1) the head
half runs a position ahead: card A could write position p+1 into the single buffer before card B's copy of position p
had read it - and only MTP mode hung (no-spec 4/4 clean; the head->tail hop, already 2 slots by p & 1, 4/4 clean).
Backups in <raw>/../pre-fix23/.  Idempotent."""
import sys, pathlib, shutil
raw = pathlib.Path(sys.argv[1]); bk = raw.parent / "pre-fix23"; bk.mkdir(exist_ok=True)
p = raw / "src/core/glm_fast_path.dp.cpp"
s = p.read_text(encoding="utf-8", errors="surrogateescape")
subs = [
    ("DPCT_CHECK_ERROR(F->hop_h = sycl::malloc_host<float>(\n                             (size_t)g.hc * E, dpct::get_in_order_queue())) !=",
     "DPCT_CHECK_ERROR(F->hop_h = sycl::malloc_host<float>(   // SYCL port (fixups23): 4 slots (hop_to_next's ring)\n                             (size_t)4 * g.hc * E, dpct::get_in_order_queue())) !=", 1),
    ("    maya_kcopy(FA->cs, FA->hop_h, state_, hop);",
     "    float* const hop_slot = FA->hop_h + (size_t) (p & 3) * g_.hc * g_.n_embd;   // SYCL port (fixups23): ring by position\n    maya_kcopy(FA->cs, hop_slot, state_, hop);", 1),
    ("    maya_kcopy(FB->cs, B->state_, FA->hop_h, hop);\n    return B->fast_layers(p, true, err);",
     "    maya_kcopy(FB->cs, B->state_, hop_slot, hop);\n    return B->fast_layers(p, true, err);", 1),
]
if "fixups23" not in s:
    for old, new, n in subs:
        assert s.count(old) == n, (old[:70], s.count(old))
    shutil.copy(p, bk / "glm_fast_path.dp.cpp")
    for old, new, n in subs: s = s.replace(old, new)
    p.write_text(s, encoding="utf-8", errors="surrogateescape"); print("  hop ring")
else: print("  already")
