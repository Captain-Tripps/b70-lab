"""Keep the checkpoints a conversation taken back from a slot starts with, instead of dropping all of them.
Opt-in: STRATA_GLM_SLOT_KEEP_CKPTS=1. Without it the engine behaves as before."""
import sys
from pathlib import Path

p = Path(sys.argv[1]) / 'src' / 'program' / 'generate.cpp'
s = p.read_bytes().decode('utf-8')
old = "            if (reuse > 0) ckpt_drop_past(0);   // another conversation's state now\n"
new = (
    "            if (reuse > 0) {   // another conversation's state now\n"
    "                // Its DSA caches below `reuse` are this prompt's tokens, so a checkpoint those tokens start with\n"
    "                // still holds (a checkpoint keeps only the KDA states and the open pool at its position).\n"
    "                static const bool keep_ckpts = [] {\n"
    "                    const char* v = getenv(\"STRATA_GLM_SLOT_KEEP_CKPTS\");\n"
    "                    return v != nullptr && atoi(v) != 0;\n"
    "                }();\n"
    "                if (!keep_ckpts) ckpt_drop_past(0);\n"
    "                else\n"
    "                    for (auto& c : ckpts)\n"
    "                        if (c.tokens.size() > reuse || !std::equal(c.tokens.begin(), c.tokens.end(), prompt.begin()))\n"
    "                            c.tokens.clear();\n"
    "            }\n"
)
crlf = '\r\n' in s
if crlf:
    old = old.replace('\n', '\r\n'); new = new.replace('\n', '\r\n')
if s.count(old) != 1:
    sys.exit(f'anchor matched {s.count(old)} times')
p.write_bytes(s.replace(old, new).encode('utf-8'))
print('patched', p, 'crlf' if crlf else 'lf')
