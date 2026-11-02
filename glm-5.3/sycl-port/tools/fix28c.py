import pathlib
p = pathlib.Path(r"<work>\sycl-raw4\src\core\glm_layer_graphs.hpp")
t = p.read_text(encoding="utf-8", errors="surrogateescape")
nl = "\r\n" if "\r\n" in t else "\n"
if "MAYA_GRAPH_LOG" not in t:
    t = t.replace("#include <string>" + nl, "#include <string>" + nl + "#include <cstdio>" + nl + "#include <cstdlib>" + nl, 1)
    a = "        replayed = false;" + nl
    assert t.count(a) == 1
    t = t.replace(a, a + "        static const bool glog = std::getenv(\"MAYA_GRAPH_LOG\") != nullptr;   // SYCL port (fixups28, debug)" + nl, 1)
    for old, tag in [("            ++invalidations;" + nl, "invalidate"), ("            ++replays;" + nl, "replay"), ("        ++captures;" + nl, "capture")]:
        assert t.count(old) == 1, old
        ind = old[:len(old) - len(old.lstrip())]
        t = t.replace(old, old + ind + "if (glog) { std::fprintf(stderr, \"graph %s layer %d (%p)\n\", \"" + tag + "\", layer, (void*) this); std::fflush(stderr); }" + nl, 1)
    p.write_text(t, encoding="utf-8", errors="surrogateescape"); print("log in")
