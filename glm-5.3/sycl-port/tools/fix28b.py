import pathlib
p = pathlib.Path(r"<work>\sycl-raw4\src\core\glm_fast_path.dp.cpp")
t = p.read_text(encoding="utf-8", errors="surrogateescape")
old = "        if (graphs && Ly.recr) {\n"
if old not in t: old = old.replace("\n", "\r\n")
assert t.count(old) == 1, t.count(old)
new = old.replace("graphs && Ly.recr", "graphs && Ly.recr && maya_graph_layer(dev_, il - l0_)")
t = t.replace(old, new)
# helper before fast_layers
anchor = "bool Glm5Model::fast_layers(int64_t p, bool hop_in, std::string &err) try {"
helper = ("// SYCL port (fixups28, debug): MAYA_KDA_GRAPH_DEVS=<bitmask of cards>, MAYA_KDA_GRAPH_N=<first n layers of a part>\n"
          "static bool maya_graph_layer(int dev, int li) {\n"
          "    static const int devs = getenv(\"MAYA_KDA_GRAPH_DEVS\") ? std::atoi(getenv(\"MAYA_KDA_GRAPH_DEVS\")) : -1;\n"
          "    static const int n = getenv(\"MAYA_KDA_GRAPH_N\") ? std::atoi(getenv(\"MAYA_KDA_GRAPH_N\")) : 1 << 20;\n"
          "    return ((devs >> dev) & 1) != 0 && li < n;\n"
          "}\n")
assert t.count(anchor) == 1
t = t.replace(anchor, helper + anchor)
p.write_text(t, encoding="utf-8", errors="surrogateescape"); print("filters in")
