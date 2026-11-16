"""L13: the GLM prompt path's dense projections (hgemm_q in src/core/glm_prefill.dp.cpp) on the ESIMD grouped GEMM.

usage: python patch_dense.py <tree>

hgemm_q dequantizes each weight slab to f16 for every chunk and calls oneMKL. With STRATA_GLM_DENSE_ESIMD=1 a
quantized weight (not BF16 / EXL3) with beta 0 and ldy == N instead goes to maya_fg_grouped as a grouped product
whose "experts" are 64-token pieces of the chunk that all read the same weight (expert stride 0): the fork's shape
gate takes at most 64 rows an active expert on average. The f16 activations are widened to an f32 scratch (the
fork packs f32 itself). A declined call falls through to the old path. Unset, the binary runs the old path."""
import pathlib, sys

p = pathlib.Path(sys.argv[1]) / 'src' / 'core' / 'glm_prefill.dp.cpp'
c = p.read_text(encoding='utf-8')
if 'STRATA_GLM_DENSE_ESIMD' in c:
    sys.exit('already patched')

helper = r'''
extern "C" int maya_fg_type_ok(int type);
extern "C" int maya_fg_grouped(void* queue, int type, const void* w, size_t stride, const float* x, float* dst,
                               const int64_t* offs, int64_t n_as, int64_t M, int64_t K);

namespace strata::core {
namespace {
// L13: dense prompt products on the ESIMD grouped GEMM (STRATA_GLM_DENSE_ESIMD=1; ..._ROWS = piece rows, <= 64)
bool dense_esimd_on() {
    static const bool on = [] {
        const char* v = std::getenv("STRATA_GLM_DENSE_ESIMD");
        return v != nullptr && std::atoi(v) != 0;
    }();
    return on;
}
int dense_esimd_rows() {
    static const int r = [] {
        const char* v = std::getenv("STRATA_GLM_DENSE_ESIMD_ROWS");
        const int x = v != nullptr ? std::atoi(v) : 64;
        return x < 1 || x > 64 ? 64 : x;
    }();
    return r;
}
struct DenseEsimdScratch {
    float* x = nullptr;
    size_t cap = 0;
    std::vector<int64_t> offs;
};
// Y[t][N] = X16[t][K] . deq(W)[N][K]^T through the grouped kernel; false when it declines (Y untouched)
bool dense_esimd(dpct::queue_ptr q, int type, const void* w, const uint16_t* X16, int ldx, float* Y, int T, int N,
                 int K) {
    if (T <= 0 || maya_fg_type_ok(type) == 0) return false;
    static std::mutex mu;
    static std::map<sycl::queue*, DenseEsimdScratch> all;
    DenseEsimdScratch* d;
    {
        std::lock_guard<std::mutex> g(mu);
        d = &all[q];
    }
    const size_t need = (size_t) T * (size_t) K;
    if (d->cap < need) {
        if (d->x != nullptr) {
            q->wait();   // the in-order queue's earlier users of the old buffer
            sycl::free(d->x, *q);
        }
        d->x = sycl::malloc_device<float>(need, *q);
        d->cap = d->x != nullptr ? need : 0;
        if (d->x == nullptr) return false;
    }
    float* x = d->x;
    q->parallel_for(sycl::range<2>((size_t) T, (size_t) K), [=](sycl::id<2> i) {
        const size_t t = i[0], k = i[1];
        x[t * (size_t) K + k] = (float) sycl::bit_cast<sycl::half>(X16[t * (size_t) ldx + k]);
    });
    const int P = dense_esimd_rows();
    const int64_t n_as = (T + P - 1) / P;
    d->offs.resize((size_t) n_as + 1);
    for (int64_t e = 0; e <= n_as; ++e) d->offs[(size_t) e] = std::min<int64_t>(e * P, T);
    return maya_fg_grouped((void*) q, type, w, 0, x, Y, d->offs.data(), n_as, N, K) != 0;
}
}  // namespace
}  // namespace strata::core
'''
anchor = '\nnamespace strata::core {\n'
assert c.count(anchor) >= 1
i = c.index(anchor)
if '#include <mutex>' not in c:
    c = c.replace('#include <map>\n', '#include <map>\n#include <mutex>\n', 1)
    i = c.index(anchor)
c = c[:i] + '\n' + helper + c[i:]

old = '        const bool x3w = w.type == strata::kernels::exl3::kTypeEXL3;\n'
assert c.count(old) == 1
new = old + ('        if (dense_esimd_on() && !x3w && w.type != gf::kTypeBF16 && beta == 0.0f && ldy == N &&\n'
             '            dense_esimd(s, w.type, w.q, X16, ldx, Y, Tn, N, Kd))\n'
             '            return;\n')
c = c.replace(old, new, 1)
p.write_text(c, encoding='utf-8', newline='\n')
print('patched', p)
