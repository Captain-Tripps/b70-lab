#!/usr/bin/env python3
"""Maya GLM port, round 10: with a whole token queued ahead, the decode hangs at a random MoE answer (B70, Level Zero,
2026-10-31) - most likely a cross-queue barrier the service records behind the queued token, which includes the wait
kernel that waits for that very answer. Waiting for the compute queue at each layer keeps the queue one layer deep
(the per-kernel-synced run decoded 16 correct tokens). MAYA_SYCL_LAYER_SYNC=0 turns it off. Idempotent."""
import sys, pathlib
p = pathlib.Path(sys.argv[1]).resolve() / "src/core/glm_fast_path.dp.cpp"
s = p.read_text(encoding="utf-8", errors="surrogateescape")
a = "    for (int il = l0_; il < l1_; ++il) {\n        const auto& Ly = F->L[(size_t) il];\n"
i = s.index("bool Glm5Model::fast_layers(")
j = s.index(a, i) + len(a)
code = ('        {   // SYCL port (fixups10): one layer in flight - see maya_fixups10.py\n'
        '            static const bool layer_sync = [] { const char* v = getenv("MAYA_SYCL_LAYER_SYNC"); return v == nullptr || std::atoi(v) != 0; }();\n'
        '            if (layer_sync && Ly.moe) s->wait();\n'
        '        }\n')
if "fixups10" not in s:
    s = s[:j] + code + s[j:]
    print("  glm_fast_path.dp.cpp: layer sync added")
else:
    print("  already applied")
p.write_text(s, encoding="utf-8", errors="surrogateescape")
