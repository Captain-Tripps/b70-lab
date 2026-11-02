import sys
p = sys.argv[1]
L = open(p, encoding="utf-8").read().split("\n")
BS = chr(92); Q = chr(34)
i = next(k for k, l in enumerate(L) if "if (F->md.resp == nullptr)" in l)
assert "F->md.resp = resp_m;" in L[i + 2]
ind = L[i][:len(L[i]) - len(L[i].lstrip())]
L[i:i + 3] = [
    ind + Q + "    if (resp_m == nullptr) { err = " + BS + Q + "glm fast: the routing response mirror did not allocate" + BS + Q + "; return false; }" + BS + "n" + Q,
    ind + Q + "    dpct::get_in_order_queue().memset(resp_m, 0, sizeof(gf::MoeResponse)).wait();" + BS + "n" + Q,
    ind + Q + "    F->md.resp = resp_m;" + BS + "n" + Q + ")",
]
open(p, "w", encoding="utf-8").write("\n".join(L))
