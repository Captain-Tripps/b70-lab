#!/usr/bin/env python3
"""Maya GLM port, round 12: the split parts' hop copies (a device buffer <-> a pinned host buffer) become kernels.
Same B70/Windows/L0 rule as fixups11: a USM host copy queued behind a running kernel blocks every other host copy in
the context until that kernel ends, and the hops sit behind the MoE wait kernels.  Windows shares one context across the
GPUs (dpct strata_device_context), so either card's kernel can use the pinned buffer.  Idempotent."""
import re, sys, pathlib
root = pathlib.Path(sys.argv[1]).resolve()
H = root / "include/maya_compat.hpp"
h = H.read_text(encoding="utf-8")
if "maya_kcopy" not in h:
    h += ("\n// SYCL port (fixups12): a copy as a kernel - on B70/Windows/L0 a USM host<->device copy queued behind a running\n"
          "// kernel blocks every other host copy in the context until that kernel ends (spin4.cpp)\n"
          "inline sycl::event maya_kcopy(sycl::queue* q, void* dst, const void* src, size_t bytes) {\n"
          "    if (bytes % 4 == 0) {\n"
          "        unsigned* d = (unsigned*) dst; const unsigned* s = (const unsigned*) src;\n"
          "        return q->parallel_for(sycl::range<1>(bytes / 4), [=](sycl::id<1> i) { d[i] = s[i]; });\n"
          "    }\n"
          "    unsigned char* d = (unsigned char*) dst; const unsigned char* s = (const unsigned char*) src;\n"
          "    return q->parallel_for(sycl::range<1>(bytes), [=](sycl::id<1> i) { d[i] = s[i]; });\n"
          "}\n")
    H.write_text(h, encoding="utf-8")
assert "#pragma once" in h or "#ifndef" in h, "maya_compat.hpp needs a guard"
recv = re.compile(r"((?:strata::q_of\([\w]+\))|(?:[\w]+(?:->\w+)*))->memcpy\(")
total = 0
for p in sorted((root / "src/core").glob("*.dp.cpp")):
    s = p.read_text(encoding="utf-8", errors="surrogateescape")
    out, i, n = [], 0, 0
    for m in recv.finditer(s):
        # the argument list up to the matching paren
        j, depth = m.end(), 1
        while depth:
            depth += {"(": 1, ")": -1}.get(s[j], 0); j += 1
        args = s[m.end():j - 1]
        if ".data()" in args.split(",")[0]:
            continue   # a std::vector (pageable): a kernel cannot touch it - stays a copy
        if "hop" not in args.split(",")[0] + args.split(",")[1] if args.count(",") >= 2 else True:
            continue
        out.append(s[i:m.start()]); out.append("maya_kcopy(" + m.group(1) + ", " + args + ")"); i = j; n += 1
    if n:
        out.append(s[i:]); t = "".join(out)
        if '#include "maya_compat.hpp"' not in t:
            k = t.index("#include"); t = t[:k] + '#include "maya_compat.hpp"   // maya_kcopy (fixups12)\n' + t[k:]
        p.write_text(t, encoding="utf-8", errors="surrogateescape")
        print(f"  {p.name}: {n} hop copies"); total += n
print(f"  total {total}")
