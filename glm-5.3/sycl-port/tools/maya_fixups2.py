#!/usr/bin/env python3
"""Maya GLM port, round 2: file-specific fixes (after maya_fixups.py). Idempotent."""
import re, sys, pathlib
root = pathlib.Path(sys.argv[1]).resolve()
changed = 0
def edit(rel, fn):
    global changed
    p = root / rel
    s = p.read_text(encoding="utf-8", errors="surrogateescape"); t = fn(s)
    if t != s:
        p.write_text(t, encoding="utf-8", errors="surrogateescape"); changed += 1; print("  fixed", rel)

def generic(s):
    # malloc_host into a pointer lvalue: decltype of a named variable is a reference
    s = re.sub(r"\(decltype\(([^()]+)\)\)", r"(std::remove_reference_t<decltype(\1)>)", s)
    # destroy_queue takes a reference: give the cast a name
    s = re.sub(r"(dpct::get_current_device\(\)\.destroy_queue)\(\((?:cudaStream_t|dpct::queue_ptr)\)(\w+)\);",
               r"{ dpct::queue_ptr q_ = (dpct::queue_ptr)\2; \1(q_); }", s)
    # cublasGemmEx -> dpct::blas::gemm (same argument order, no algo argument)
    s = re.sub(r"\bcublasGemmEx\(((?:[^()]|\([^()]*\))*?),\s*dpct::compute_type::f32,\s*99\)",
               r"DPCT_CHECK_ERROR(dpct::blas::gemm(\1, dpct::compute_type::f32))", s, flags=re.S)
    return s
for p in list((root / "src").rglob("*.cpp")):
    edit(str(p.relative_to(root)), generic)

# glm_prefill: the fp32 GEMMs (warm-up got void* operands; the main one stayed cuBLAS)
def prefill(s):
    s = s.replace("16, 16, 16, one, wa, 16,\n                    wb, 16, zero, wc, 16)",
                  "16, 16, 16, one, (const float *)wa, 16,\n                    (const float *)wb, 16, zero, (float *)wc, 16)")
    s = re.sub(r"cublasSgemm\(S->blas, (oneapi::mkl::transpose::\w+),\s*(oneapi::mkl::transpose::\w+), n, Tn, Kd, &alpha,\s*S->w32, Kd, X, ldx, &zero, Y \+ r0, ldy\)",
               r"DPCT_CHECK_ERROR(oneapi::mkl::blas::column_major::gemm(S->blas->get_queue(), \1, \2, n, Tn, Kd, alpha, S->w32, Kd, X, ldx, zero, Y + r0, ldy))", s)
    return s
edit("src/core/glm_prefill.dp.cpp", prefill)

# glm_model: dpct left the host-side weight lookup W("...") inside kernel lambdas; hoist it into the submit body
def hoist_w(s):
    pat = re.compile(r"(submit\(\[&\]\(sycl::handler &cgh\) \{\n)(.*?)(\n(\s*)cgh\.parallel_for\(.*?\}\);\n\s*\}\);)", re.S)
    def one(m):
        body = m.group(3)
        names = list(dict.fromkeys(re.findall(r'\bW\("([\w.]+)"\)', body)))
        if not names: return m.group(0)
        decl = "".join(f'{m.group(4)}auto W_{re.sub(r"\W", "_", n)} = W("{n}");\n' for n in names)
        for n in names:
            body = body.replace(f'W("{n}")', "W_" + re.sub(r"\W", "_", n))
        return m.group(1) + m.group(2) + "\n" + decl.rstrip("\n") + body
    return pat.sub(one, s)
edit("src/core/glm_model.dp.cpp", hoist_w)

# windef.h defines `near`
edit("src/kernels/sampler_parity.cpp", lambda s: re.sub(r"\bnear\b", "near_ok", s))

# glm_batch: Volta/Ampere tensor-core PTX (mma.sync, ldmatrix). DPCT_COMPATIBILITY_TEMP is 900 on SYCL, which
# selects the PTX; take the scalar/stub side. The XMX joint_matrix port is follow-up work.
edit("src/kernels/cuda/glm_batch.dp.cpp", lambda s: s
     .replace("#if defined(DPCT_COMPATIBILITY_TEMP) && DPCT_COMPATIBILITY_TEMP >= 800", "#if 0   // SYCL: PTX ldmatrix/mma not ported")
     .replace("#if defined(DPCT_COMPATIBILITY_TEMP) && DPCT_COMPATIBILITY_TEMP < 700", "#if 1   // SYCL: Volta mma/wmma not ported (stub)"))

# qsa_parity: graph node introspection has no SYCL API (debug count only)
edit("src/kernels/qsa_parity.cpp", lambda s: s.replace('check(cudaGraphGetNodes(g2, nullptr, &nodes2), "nodes");', 'nodes2 = g2->get_nodes().size(); check(0, "nodes");'))
print(changed, "files changed")
