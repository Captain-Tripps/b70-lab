"""L5 (prefill indexer): an XMX version of the GLM DSA indexer score (dsa_score in src/kernels/cuda/glm_batch.dp.cpp),
after the XMX lightning indexer of llama.cpp#31313 (head 976b63c).

usage: python patch_dsa.py <tree>

score[t][p] = sum_h relu(iq[t][h] . pooled[p]) * iw[t][h], 32 heads, key 128, written for p < (p0 + t + 1) / kpool
only (as the FP32 tiled kernel). With STRATA_GLM_DSA_XMX=1: q is staged to f16 (padded to whole 32-token blocks),
a work-group packs 64 pooled keys into SLM as f16 VNNI pairs once and reuses them for every head and token block;
per head a sub-group runs 16x16x16 f16 joint_matrix products for its 16 keys (two 16-token tiles), then relu * w
into per-lane sums. Unset, the FP32 tiled kernel runs as before."""
import pathlib, sys

p = pathlib.Path(sys.argv[1]) / 'src' / 'kernels' / 'cuda' / 'glm_batch.dp.cpp'
c = p.read_text(encoding='utf-8')
if 'STRATA_GLM_DSA_XMX' in c:
    sys.exit('already patched')

inc = '#include <sycl/sycl.hpp>\n'
assert c.count(inc) >= 1
c = c.replace(inc, inc + '#include <sycl/ext/oneapi/matrix/matrix.hpp>\n#include <map>\n#include <mutex>\n', 1)

kernel = r'''
// L5: the indexer score on XMX (STRATA_GLM_DSA_XMX=1), after llama.cpp#31313's lightning indexer
namespace dsa_xmx {
namespace mx = sycl::ext::oneapi::experimental::matrix;
constexpr int H = 32, K = 128, TM = 16, TN = 16, TK = 16, SG = 16, NSG = 4, KEYS = NSG * TN, MT = 2,
              TOK = MT * TM, NT = 4, WG_TOK = NT * TOK;
bool on() {
    static const bool v = [] {
        const char* e = getenv("STRATA_GLM_DSA_XMX");
        return e != nullptr && std::atoi(e) != 0;
    }();
    return v;
}
struct Scratch {
    sycl::half* q = nullptr;
    size_t cap = 0;
};
bool run(const float* iq, const float* pooled, const float* iw, int p0, int kpool, int T, int max_vis, float* score,
         int score_ld, dpct::queue_ptr s) {
    static std::mutex mu;
    static std::map<sycl::queue*, Scratch> all;
    Scratch* d;
    {
        std::lock_guard<std::mutex> g(mu);
        d = &all[s];
    }
    const int Tpad = (T + TOK - 1) / TOK * TOK;
    const size_t need = (size_t) H * Tpad * K;
    if (d->cap < need) {
        if (d->q != nullptr) {
            s->wait();
            sycl::free(d->q, *s);
        }
        d->q = sycl::malloc_device<sycl::half>(need, *s);
        d->cap = d->q != nullptr ? need : 0;
        if (d->q == nullptr) return false;
    }
    sycl::half* q16 = d->q;
    // q16[h][t][e], rows past T zero
    s->parallel_for(sycl::range<3>((size_t) H, (size_t) Tpad, (size_t) K), [=](sycl::id<3> i) {
        const int h = (int) i[0], t = (int) i[1], e = (int) i[2];
        const float v = t < T ? iq[((size_t) t * H + h) * K + e] : 0.0f;
        q16[((size_t) h * Tpad + t) * K + e] = (sycl::half) v;
    });
    const int n_kv_groups = (max_vis + KEYS - 1) / KEYS, n_tok_groups = (T + WG_TOK - 1) / WG_TOK;
    s->submit([&](sycl::handler& cgh) {
        sycl::local_accessor<sycl::half, 1> kt(K * KEYS, cgh);         // [e / 2][key][2]
        sycl::local_accessor<float, 1> ct(NSG * TOK * TN, cgh);       // per sub-group [token][key]
        cgh.parallel_for(
            sycl::nd_range<2>(sycl::range<2>((size_t) n_tok_groups, (size_t) n_kv_groups * NSG * SG),
                              sycl::range<2>(1, NSG * SG)),
            [=](sycl::nd_item<2> it) [[sycl::reqd_sub_group_size(16)]] {
                const auto sg = it.get_sub_group();
                const int sg_id = (int) sg.get_group_linear_id(), lane = (int) sg.get_local_linear_id();
                const int t_wg = (int) it.get_group(0) * WG_TOK, kv0 = (int) it.get_group(1) * KEYS;
                const int t_end = sycl::min(t_wg + WG_TOK, T);
                if (kv0 >= (p0 + t_end) / kpool) return;   // no key of the tile is visible to any token (uniform)
                for (int key = (int) it.get_local_linear_id(); key < KEYS; key += NSG * SG) {
                    const int pk = kv0 + key;
                    for (int e = 0; e < K; e += 2) {
                        float v0 = 0.0f, v1 = 0.0f;
                        if (pk < max_vis) {
                            v0 = pooled[(size_t) pk * K + e];
                            v1 = pooled[(size_t) pk * K + e + 1];
                        }
                        kt[((size_t) (e / 2) * KEYS + key) * 2 + 0] = (sycl::half) v0;
                        kt[((size_t) (e / 2) * KEYS + key) * 2 + 1] = (sycl::half) v1;
                    }
                }
                sycl::group_barrier(it.get_group());
                const auto q_ptr = sycl::address_space_cast<sycl::access::address_space::global_space,
                                                            sycl::access::decorated::no>((const sycl::half*) q16);
                const auto b_ptr = kt.template get_multi_ptr<sycl::access::decorated::no>() + sg_id * TN * 2;
                const auto c_ptr = ct.template get_multi_ptr<sycl::access::decorated::no>() + sg_id * TOK * TN;
                const float* c_sg = &ct[(size_t) sg_id * TOK * TN];
                const int p = kv0 + sg_id * TN + lane;
                for (int t0 = t_wg; t0 < t_end; t0 += TOK) {
                    float acc_s[TOK];
#pragma unroll
                    for (int t = 0; t < TOK; ++t) acc_s[t] = 0.0f;
                    for (int h = 0; h < H; ++h) {
                        mx::joint_matrix<sycl::sub_group, float, mx::use::accumulator, TM, TN> acc[MT];
#pragma unroll
                        for (int mt = 0; mt < MT; ++mt) mx::joint_matrix_fill(sg, acc[mt], 0.0f);
                        const size_t a_off = ((size_t) h * Tpad + t0) * K;
#pragma unroll
                        for (int kk = 0; kk < K / TK; ++kk) {
                            mx::joint_matrix<sycl::sub_group, sycl::half, mx::use::b, TK, TN, mx::layout::ext_intel_packed> b;
                            mx::joint_matrix_load(sg, b, b_ptr + (size_t) kk * TK * KEYS, KEYS * 2);
#pragma unroll
                            for (int mt = 0; mt < MT; ++mt) {
                                mx::joint_matrix<sycl::sub_group, sycl::half, mx::use::a, TM, TK, mx::layout::row_major> a;
                                mx::joint_matrix_load(sg, a, q_ptr + a_off + (size_t) mt * TM * K + kk * TK, K);
                                mx::joint_matrix_mad(sg, acc[mt], a, b, acc[mt]);
                            }
                        }
#pragma unroll
                        for (int mt = 0; mt < MT; ++mt)
                            mx::joint_matrix_store(sg, acc[mt], c_ptr + (size_t) mt * TM * TN, TN, mx::layout::row_major);
                        sycl::group_barrier(sg);
#pragma unroll
                        for (int t = 0; t < TOK; ++t) {
                            const int tok = sycl::min(t0 + t, T - 1);
                            acc_s[t] += sycl::fmax(c_sg[t * TN + lane], 0.0f) * iw[(size_t) tok * H + h];
                        }
                        sycl::group_barrier(sg);
                    }
#pragma unroll
                    for (int t = 0; t < TOK; ++t) {
                        const int tok = t0 + t;
                        if (tok < T && p < (p0 + tok + 1) / kpool) score[(size_t) tok * score_ld + p] = acc_s[t];
                    }
                }
            });
    });
    return true;
}
}  // namespace dsa_xmx

'''
anchor = 'void dsa_score(const float *iq, const float *pooled, const float *iw,\n'
assert c.count(anchor) == 1
c = c.replace(anchor, kernel + anchor, 1)

old = '    if (T <= 0 || max_vis <= 0) return;\n    // STRATA_GLM_DSA_SCORE=0'
assert c.count(old) == 1
c = c.replace(old, '    if (T <= 0 || max_vis <= 0) return;\n'
              '    if (idx_heads == dsa_xmx::H && key_dim == dsa_xmx::K && dsa_xmx::on() &&\n'
              '        dsa_xmx::run(iq, pooled, iw, p0, kpool, T, max_vis, score, score_ld, s))\n'
              '        return;\n    // STRATA_GLM_DSA_SCORE=0', 1)
p.write_text(c, encoding='utf-8', newline='\n')
print('patched', p)
