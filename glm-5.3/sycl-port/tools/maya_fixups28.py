"""Maya GLM port, round 28: the KDA layers' graphs (fast_layers' LayerGraphs, a SYCL command graph per recurrent
layer, captured once and replayed) in a split / MTP decode.  After fixups25/26 a card's ~350 launches a token are
queued by the host at ~20 us each and the card runs behind that queueing (head: DEVICE 9.1 ms, gap 11.2 ms a token).
A KDA layer's launches take no position: a replay is one submit.  The CUDA original kept the graphs to one-part,
non-MTP decode; MAYA_KDA_GRAPH=1 drops those three conditions (n_parts_, hop_in, mtp_il_ - none reaches the captured
body) and keeps the rest.  Opt-in until soaked.  Backups in <raw>/../pre-fix28/.  Idempotent."""
import sys, pathlib, shutil
raw = pathlib.Path(sys.argv[1]); bk = raw.parent / "pre-fix28"; bk.mkdir(exist_ok=True)
p = raw / "src/core/glm_fast_path.dp.cpp"
t = p.read_text(encoding="utf-8", errors="surrogateescape")
old = """    const bool graphs = graph_opt && std::atoi(graph_opt) != 0 && n_parts_ == 1 && !hop_in &&
                        mtp_il_ < 0 && !F->prof_on && !dumps && F->max_pf == 0 && F->n_ahead == 0 &&
                        getenv("GLM_DUMP_H") == nullptr && cap_d_ == nullptr;
"""
new = """    // SYCL port (fixups28): MAYA_KDA_GRAPH=1 - the KDA graphs in a split / MTP decode too
    static const bool maya_graph = [] { const char* v = getenv("MAYA_KDA_GRAPH"); return v != nullptr && v[0] != '0'; }();
    const bool graphs = (maya_graph || (graph_opt && std::atoi(graph_opt) != 0 && n_parts_ == 1 && !hop_in &&
                        mtp_il_ < 0)) && !F->prof_on && !dumps && F->max_pf == 0 && F->n_ahead == 0 &&
                        getenv("GLM_DUMP_H") == nullptr && cap_d_ == nullptr;
    if (maya_graph) {
        static int said = 0;
        if (said++ < 8) std::fprintf(stderr, "glm kda graphs CUDA%d: %s (prof %d dumps %d max_pf %d n_ahead %d cap %d)\n",
                                     dev_, graphs ? "on" : "off", (int) F->prof_on, (int) dumps, (int) F->max_pf,
                                     (int) F->n_ahead, (int) (cap_d_ != nullptr));
    }
"""
if "fixups28" not in t:
    assert t.count(old) == 1, t.count(old)
    shutil.copy(p, bk / "glm_fast_path.dp.cpp")
    p.write_text(t.replace(old, new), encoding="utf-8", errors="surrogateescape"); print("  kda graphs in split/MTP (MAYA_KDA_GRAPH)")
else: print("  already")
