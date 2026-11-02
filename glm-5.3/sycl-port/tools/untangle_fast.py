#!/usr/bin/env python3
"""glm_fast: drop the ggml tables dpct threaded through parameters/captures (macro bodies included). Run on the
pre-round-3 copy; also strips undeducible kernel names and fixes the one 2-argument table helper."""
import re, sys
src, dst = sys.argv[1], sys.argv[2]
s = open(src, encoding="utf-8", errors="surrogateescape", newline="").read()
crlf = "\r\n" in s
s = s.replace("\r\n", "\n")
J = "\x01"                      # a macro line continuation, treated as whitespace below
s = s.replace("\\\n", J)
W = r"[\s" + J + r"]*"
T = r"(iq2xxs_grid|iq2xs_grid|iq2s_grid|iq3xxs_grid|iq3s_grid|iq1s_grid_gpu|kmask_iq2xs|ksigns_iq2xs|ksigns64|kvalues_iq4nl)"
TY = r"(const )?(uint64_t|uint32_t|uint8_t|int8_t) \*"
s = re.sub(r"parallel_for<" + W + r"dpct_kernel_name<.*?>>\(", "parallel_for(", s, flags=re.S)
s = re.sub(r"\b" + T + r"\.get_ptr\(\)", r"\1", s)
s = re.sub(r"[ \t]*" + T + r"\.init\([^;]*\);[ \t]*(" + J + r"|\n)", "", s)
s = re.sub(r"[ \t]*auto " + T + r"_ptr_ct\d+ = " + T + r";[ \t]*(" + J + r"|\n)", "", s)
s = re.sub(r"," + W + TY + T + r"\b(?!\s*\[)", "", s)
s = re.sub(r"\(" + W + TY + T + W + r"\)", "()", s)
s = re.sub(r"," + W + T + r"_ptr_ct\d+\b", "", s)
s = re.sub(r"\(" + W + T + r"_ptr_ct\d+" + W + r"\)", "()", s)
# plain table arguments in calls (not indexing, not declarations); the GLMF_IQ_F invocations are restored below
s = re.sub(r"," + W + T + r"\b(?=" + W + r"[,)])", "", s)
s = s.replace("get_int_from_table_16(aux_q4);", "get_int_from_table_16(aux_q4, kvalues_iq4nl);")
s = s.replace(J, "\\\n")
for t, b, st, tb in [(17, "block_iq2_xs", 2, "iq2xs_grid"), (22, "block_iq2_s", 2, "iq2s_grid"),
                     (21, "block_iq3_s", 2, "iq3s_grid"), (29, "block_iq1_m", 1, "iq1s_grid_gpu")]:
    s = s.replace(f"GLMF_IQ_F({t}, {b}, {st})\n", f"GLMF_IQ_F({t}, {b}, {st}, {tb})\n")
if crlf:
    s = s.replace("\n", "\r\n")
open(dst, "w", encoding="utf-8", errors="surrogateescape", newline="").write(s)
