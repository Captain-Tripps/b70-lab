import pathlib
p = pathlib.Path(r"<work>\sycl-raw4\src\core\glm_fast_path.dp.cpp")
t = p.read_text(encoding="utf-8", errors="surrogateescape")
nl = "\r\n" if "\r\n" in t else "\n"
NL = chr(92) + "n"
def tr(msg):
    return ('{ static const bool st_ = getenv("MAYA_SPEC_TRACE") != nullptr; static int sn_ = 0; if (st_ && sn_++ < 60) { std::fprintf(stderr, "STRACE ' + msg + NL + '", (long long) p); std::fflush(stderr); } }')
edits = [
 ("bool Glm5Model::spec_head(int64_t p, int32_t token, std::string& err) {" + nl, "head enter p=%lld"),
 ("bool Glm5Model::spec_tail(Glm5Model* head, int64_t p, std::string& err) {" + nl, "tail enter p=%lld"),
]
if "STRACE" not in t:
    for a, m in edits:
        assert t.count(a) == 1, a
        t = t.replace(a, a + "    " + tr(m) + nl, 1)
    # inside spec_head: after the head parts' waits, after own wait, after layers
    for a, m in [("    lap(0);" + nl + "    if (sprof) {" + nl + "        if (spec_ev_[0] == nullptr)", "head waited p=%lld"),
                 ("    if (!layers_ok) return false;" + nl, "head layers queued p=%lld"),
                 ("    maya_queue_wait(F->cs, head->spec_ev_hop_[sl], true);   // SYCL port (fixups17)" + nl, "tail queued wait p=%lld")]:
        assert t.count(a) == 1, (a, t.count(a))
        t = t.replace(a, a.replace(a, a) , 1)
        idx = t.index(a)
        if m.startswith("head waited"):
            t = t[:idx] + "    " + tr(m) + nl + t[idx:]
        else:
            t = t[:idx + len(a)] + "    " + tr(m) + nl + t[idx + len(a):]
    p.write_text(t, encoding="utf-8", errors="surrogateescape"); print("trace in")
else: print("already")
