#!/usr/bin/env python3
"""Maya GLM port, round 13: a queue on one GPU waiting on another GPU's event (ext_oneapi_submit_barrier) aborts in the
Windows Level Zero runtime even inside the one shared context (spin5.cpp: abort in UR; in Maya it surfaces as
UR_RESULT_ERROR_OUT_OF_RESOURCES at the first split hop).  The split parts' hops order on the host instead: wait for the
previous part's hop event, then queue the next part's layers (that GPU would sit idle until the hop anyway - a layer
split is sequential).  Only the barriers whose event belongs to ANOTHER part; same-device barriers stay.  Idempotent."""
import re, sys, pathlib
root = pathlib.Path(sys.argv[1]).resolve() / "src/core"
TAG = "// SYCL port (fixups13): cross-device barrier aborts on Windows L0 - host wait"
SITES = {
    "glm_fast_path.dp.cpp": [r"FB->cs->ext_oneapi_submit_barrier\(\{\*FA->ev_hop\}\);",
                             r"F->cs->ext_oneapi_submit_barrier\(\{\*head->spec_ev_hop_\[sl\]\}\);"],
    "glm_mtp_rows.dp.cpp": [r"s->ext_oneapi_submit_barrier\(\{\*prev->mtpw_->ev_hop\[\(size_t\)sq\]\}\);"],
    "glm_multi.dp.cpp": [r"B->fast_->cs->ext_oneapi_submit_barrier\(\{\*ca\.ev_hop\}\);"],
    "glm_prefill.dp.cpp": [r"m->fast_->cs->ext_oneapi_submit_barrier\(\{\*SP->ev_hop\}\);"],
    "glm_rows.dp.cpp": [r"B->fast_->cs->ext_oneapi_submit_barrier\(\{\*ca\.ev_hop\}\);"],
    "glm_window.dp.cpp": [r"B->fast_->cs->ext_oneapi_submit_barrier\(\{\*WA\.ev_hop\}\);",
                          r"F->cs->ext_oneapi_submit_barrier\(\{\*prev->fast_->win\.ev_tok\[sl\]\}\);"],
}
for name, pats in SITES.items():
    p = root / name
    s = p.read_text(encoding="utf-8", errors="surrogateescape")
    t = s
    for pat in pats:
        def repl(m):
            ev = re.search(r"\{\*(.+)\}\);$", m.group(0)).group(1)
            return "(" + ev + ")->wait(); " + TAG
        t, n = re.subn(pat + r"(?!\s*// SYCL port \(fixups13\))", repl, t)
        print(f"  {name}: {n} x {pat[:50]}")
    if t != s: p.write_text(t, encoding="utf-8", errors="surrogateescape")
