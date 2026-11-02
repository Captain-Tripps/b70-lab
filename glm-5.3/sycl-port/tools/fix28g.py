import pathlib
p = pathlib.Path(r"<work>\sycl-raw4\src\core\glm_fast_path.dp.cpp")
t = p.read_text(encoding="utf-8", errors="surrogateescape")
nl = "\r\n" if "\r\n" in t else "\n"
NL = chr(92) + "n"
a = "    Glm5Model* hl = spec_head_last();" + nl + "    // every part of the head group idle first"
assert t.count(a) == 1, t.count(a)
if "STRACE qstate" not in t:
    ins = ("    Glm5Model* hl = spec_head_last();" + nl +
           '    if (getenv("MAYA_SPEC_TRACE") != nullptr && p >= 6 && p <= 7) {' + nl +
           '        for (int k = 0; k < 6; ++k) {' + nl +
           '            std::fprintf(stderr, "STRACE qstate p=%lld:", (long long) p);' + nl +
           '            for (Glm5Model* m = this; m != nullptr; m = m->split_next_.get())' + nl +
           '                std::fprintf(stderr, " CUDA%d %s", m->dev_, m->fast_->cs->ext_oneapi_empty() ? "empty" : "BUSY");' + nl +
           '            std::fprintf(stderr, "' + NL + '"); std::fflush(stderr);' + nl +
           '            std::this_thread::sleep_for(std::chrono::milliseconds(500));' + nl +
           '        }' + nl +
           '    }' + nl +
           "    // every part of the head group idle first")
    t = t.replace(a, ins, 1)
    p.write_text(t, encoding="utf-8", errors="surrogateescape"); print("qstate in")
