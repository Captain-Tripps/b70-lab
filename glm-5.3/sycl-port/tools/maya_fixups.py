#!/usr/bin/env python3
"""Maya GLM port: hand fixes on top of the dpct output (after Strata's fixups.py). Idempotent."""
import re, sys, pathlib
root = pathlib.Path(sys.argv[1]).resolve()
changed = 0
SHIM = re.compile(r"\b(cudaStream_t|cudaEvent_t|cudaEventDisableTiming|cudaGraphDestroy|cudaLaunchHostFunc|cudaDeviceGetAttribute|cudaDeviceGetPCIBusId|cudaDevAttr\w+|__fadd_rn|clock64)\b")

def fix(s):
    # casts that bind to the member call instead of the pointer
    s = re.sub(r"\((cudaStream_t|dpct::queue_ptr)\)\s*(\w+)\s*->", r"((dpct::queue_ptr)\2)->", s)
    s = re.sub(r"\((cudaEvent_t|dpct::event_ptr)\)\s*(\w+)\s*->", r"((dpct::event_ptr)\2)->", s)
    # null stream: the default in-order queue
    s = s.replace("nullptr->wait()", "dpct::get_in_order_queue().wait()")
    # '#pragma unroll' that dpct separated from its loop with the nd_item fetch
    s = re.sub(r"(#pragma unroll[^\n]*)\n(\s*auto item_ct1 = sycl::ext::oneapi::this_work_item::get_nd_item<\d>\(\);)\n",
               r"\2\n\1\n", s)
    # malloc_host into a pointer: dpct wrote a literal `value_type` cast
    s = re.sub(r"\b([\w.\[\]>-]+) = \(value_type\)", r"\1 = (decltype(\1))", s)
    # kernel names declared in a namespace that never declares them: unnamed lambdas are fine in SYCL 2020
    s = re.sub(r"parallel_for<\s*dpct_kernel_name<class [\w:]+(<[^>]*>)?>>\(", "parallel_for(", s)
    # Windows DXGI LUID match: no LUID in dpct::device_info
    s = s.replace("std::memcmp(&desc.AdapterLuid, prop.luid, sizeof prop.luid) == 0", "false /* SYCL: no device LUID */")
    # %globaltimer: no device wall clock in SPIR-V
    s = re.sub(r'asm volatile\("mov\.u64 %0, %%globaltimer;" : "=l"\((\w+)\)\);', r"\1 = 0; /* SYCL: no %globaltimer */", s)
    # ternary on the memcpy stream migrated around the wrong operand
    s = re.sub(r"gs \? gs->adapt_stream\s*: adapt_stream->memcpy\(", "(gs ? gs->adapt_stream : adapt_stream)->memcpy(", s)
    if SHIM.search(s) and '"maya_compat.hpp"' not in s:
        s = s.replace("#include <dpct/dpct.hpp>\n", '#include <dpct/dpct.hpp>\n#include "maya_compat.hpp"\n', 1)
        if '"maya_compat.hpp"' not in s:
            s = '#include "maya_compat.hpp"\n' + s
    return s

for p in list((root / "src").rglob("*.cpp")) + list((root / "src").rglob("*.hpp")) + list((root / "include" / "strata").rglob("*.hpp")):
    s = p.read_text(encoding="utf-8", errors="surrogateescape"); t = fix(s)
    if t != s:
        p.write_text(t, encoding="utf-8", errors="surrogateescape"); changed += 1; print("  fixed", p.relative_to(root))
print(changed, "files changed")
