import pathlib
p = pathlib.Path(r"<work>\sycl-raw4\src\core\glm_layer_graphs.hpp")
t = p.read_text(encoding="utf-8", errors="surrogateescape")
nl = "\r\n" if "\r\n" in t else "\n"
if "MAYA_GRAPH_BAR" not in t:
    a = "            if (!it->second.graph.launch(stream, err)) return false;" + nl
    assert t.count(a) == 1
    bar = ("            { static const bool gbar = [] { const char* v = std::getenv(\"MAYA_GRAPH_BAR\"); return v == nullptr || v[0] != '0'; }();"
           "   // SYCL port (fixups28): order the replay against what follows" + nl +
           "              if (gbar) stream->ext_oneapi_submit_barrier(); }" + nl)
    t = t.replace(a, a + bar, 1)
    b = "        if (!entry.graph.end(stream, err) || !entry.graph.launch(stream, err)) {" + nl
    assert t.count(b) == 1
    t = t.replace(b, b.replace("!entry.graph.launch(stream, err)) {", "!entry.graph.launch(stream, err)) {"), 1)
    # also after the first launch
    c = "        entries_.emplace(layer, std::move(entry));" + nl
    t = t.replace(c, "        { const char* v = std::getenv(\"MAYA_GRAPH_BAR\"); if (v == nullptr || v[0] != '0') stream->ext_oneapi_submit_barrier(); }" + nl + c, 1)
    p.write_text(t, encoding="utf-8", errors="surrogateescape"); print("graph barrier in")
