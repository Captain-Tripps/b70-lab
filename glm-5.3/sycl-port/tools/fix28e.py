import pathlib
p = pathlib.Path(r"<work>\sycl-raw4\src\core\glm_fast_path.dp.cpp")
t = p.read_text(encoding="utf-8", errors="surrogateescape")
nl = "\r\n" if "\r\n" in t else "\n"
NL = chr(92) + "n"
a = "    while (F->processed.load(std::memory_order_acquire) < F->expected) cpu_relax();" + nl
assert t.count(a) == 1
if "STRACE boundary" not in t:
    pre = ('    { static const bool st_ = getenv("MAYA_SPEC_TRACE") != nullptr; static int sn_ = 0; if (st_ && sn_++ < 400) { std::fprintf(stderr, "STRACE boundary CUDA%d waited, expected %llu processed %llu' + NL + '", dev_, (unsigned long long) F->expected, (unsigned long long) F->processed.load()); std::fflush(stderr); } }' + nl)
    t = t.replace(a, pre + a, 1)
    p.write_text(t, encoding="utf-8", errors="surrogateescape"); print("boundary trace in")
