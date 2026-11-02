#!/usr/bin/env python3
"""Maya GLM port, round 14: the prompt path's two per-head strided GEMMs (MLA q_abs and the MLA output) run as one
oneMKL gemm a head.  cuBLAS's strided batch takes the heads interleaved (stride < ld * cols); oneMKL's gemm_batch
throws on that layout (status 999 every layer, wrong attention).  Same arguments, same order.  Idempotent."""
import sys, pathlib
p = pathlib.Path(sys.argv[1]).resolve() / "src/core/glm_prefill.dp.cpp"
s = p.read_text(encoding="utf-8", errors="surrogateescape")
HELPER = '''
// SYCL port (fixups14): cublasSgemmStridedBatched with the heads interleaved (stride < ld * cols), as one oneMKL gemm
// a batch entry - oneMKL's strided gemm_batch rejects that layout.  Column-major, the gemm_batch argument order.
static sycl::event maya_gemm_heads(sycl::queue& q, oneapi::mkl::transpose ta, oneapi::mkl::transpose tb, int64_t m,
                                   int64_t n, int64_t k, float alpha, const float* a, int64_t lda, int64_t sa,
                                   const float* b, int64_t ldb, int64_t sb, float beta, float* c, int64_t ldc,
                                   int64_t sc, int64_t batch) {
    sycl::event e;
    for (int64_t i = 0; i < batch; ++i)
        e = oneapi::mkl::blas::column_major::gemm(q, ta, tb, m, n, k, alpha, a + i * sa, lda, b + i * sb, ldb, beta,
                                                  c + i * sc, ldc);
    return e;
}
'''
if "maya_gemm_heads" not in s:
    n = s.count("oneapi::mkl::blas::column_major::gemm_batch(")
    assert n == 2, n
    s = s.replace("oneapi::mkl::blas::column_major::gemm_batch(", "maya_gemm_heads(")
    # the helper goes before the first function that uses it
    anchor = s.index("maya_gemm_heads(")
    fn = s.rfind("\nbool Glm5Model::", 0, anchor)
    if fn < 0:
        fn = s.rfind("\nvoid Glm5Model::", 0, anchor)
    assert fn > 0
    s = s[:fn] + "\n" + HELPER + s[fn:]
    p.write_text(s, encoding="utf-8", errors="surrogateescape")
    print("  2 per-head gemms")
else:
    print("  already")
