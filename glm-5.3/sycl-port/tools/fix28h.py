import pathlib
p = pathlib.Path(r"<work>\sycl-raw4\src\core\glm_fast_path.dp.cpp")
t = p.read_text(encoding="utf-8", errors="surrogateescape")
a = '                std::fprintf(stderr, " CUDA%d %s", m->dev_, m->fast_->cs->ext_oneapi_empty() ? "empty" : "BUSY");'
assert t.count(a) == 1
b = ('                { const FastState* Fm = m->fast_; unsigned int last = 0; for (int i = 0; i < gf::kRingSize; ++i) last = std::max(last, (unsigned int) Fm->ring_h[i].seq);'
     ' std::fprintf(stderr, " CUDA%d %s ring %u resp %u exp %llu proc %llu allres %d", m->dev_, Fm->cs->ext_oneapi_empty() ? "empty" : "BUSY", last, (unsigned int) Fm->resp_h->seq,'
     ' (unsigned long long) Fm->expected, (unsigned long long) Fm->processed.load(), (int) Fm->all_resident); }')
t = t.replace(a, b, 1)
p.write_text(t, encoding="utf-8", errors="surrogateescape"); print("ring state in")
