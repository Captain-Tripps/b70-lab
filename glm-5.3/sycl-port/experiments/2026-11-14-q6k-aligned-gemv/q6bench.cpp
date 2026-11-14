// q6bench.cpp - one-column Q6_K GEMV (the dense decode mat-vec, glmf::mv_kernel_t<14>) on the real GLM-5.3 shapes.
// Variants: V0 production copy, V1/V2 the engine's cc-6.0 aligned-word kernel (R = 2 / 4, activation in SLM),
// V3 SoA repack with production's exact per-lane calls (bit-exact), V4 V3 + activation in SLM, V5 SoA, 2 rows a warp.
// Cold weights: a pool of copies larger than L2, rotated per launch.  Output: us/launch median, GB/s, max |diff| vs V0.
#include <sycl/sycl.hpp>
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <random>
#include <vector>

struct block_q6_K { uint8_t ql[128]; uint8_t qh[64]; int8_t scales[16]; sycl::half d; };
static_assert(sizeof(block_q6_K) == 210, "q6k");
struct block_q8_1 { sycl::half2 ds; int8_t qs[32]; };
static_assert(sizeof(block_q8_1) == 36, "q81");
constexpr int MV_ROWS = 8;

static inline float warp_sum(float v) {
    auto sg = sycl::ext::oneapi::this_work_item::get_sub_group();
#pragma unroll
    for (int o = 16; o > 0; o >>= 1) v += sycl::permute_group_by_xor(sg, v, o);
    return v;
}
static inline int dp4a(int a, int b, int c) {
    const sycl::char4 va = sycl::bit_cast<sycl::char4>(a), vb = sycl::bit_cast<sycl::char4>(b);
    return c + va.x() * vb.x() + va.y() * vb.y() + va.z() * vb.z() + va.w() * vb.w();
}
static inline int m32(int q) {   // per byte q - 32, q in [0, 63] (== sub_sat with 0x20202020 there)
    return (q + 0x60606060) ^ (int) 0x80808080;
}
static inline int get_int_b2(const void* x, int i32) {
    const uint16_t* x16 = (const uint16_t*) x;
    return (int) ((uint32_t) x16[2 * i32] | ((uint32_t) x16[2 * i32 + 1] << 16));
}
static inline float h2f_dev(sycl::half h) { return (float) h; }

// ---- V0: production
static inline float dot_q6_K(const block_q6_K* w, const block_q8_1* bq8_1, int iqs) {
    const int bq8_offset = 4 * (iqs / 16) + (iqs % 16) / 8;
    const int scale_offset = 8 * (iqs / 16) + (iqs % 16) / 4;
    const int vh_shift = 2 * ((iqs % 16) / 8);
    const int vl = get_int_b2(w->ql, iqs);
    const int vh = get_int_b2(w->qh, 8 * (iqs / 16) + iqs % 8) >> vh_shift;
    const int8_t* scales = w->scales + scale_offset;
    float sumf = 0.0f;
#pragma unroll
    for (int i = 0; i < 2; ++i) {
        const int u = ((const int*) bq8_1[bq8_offset + 2 * i].qs)[iqs % 8];
        const float d8 = (float) bq8_1[bq8_offset + 2 * i].ds[0];
        const int sc = scales[4 * i];
        const int vil = (vl >> (4 * i)) & 0x0f0f0f0f;
        const int vih = ((vh >> (4 * i)) << 4) & 0x30303030;
        sumf += d8 * (dp4a(m32(vil | vih), u, 0) * sc);
    }
    return (float) w->d * sumf;
}
struct Job { const uint8_t* w; const block_q8_1* x; float* y; int n_in, n_out;
             const uint8_t *ql, *qh; const int8_t* sc; const sycl::half* d; };   // (SoA arrays for V3-V5)

static sycl::event v0(sycl::queue& q, const Job& J) {
    const int blocks = (J.n_out + MV_ROWS - 1) / MV_ROWS;
    return q.parallel_for(sycl::nd_range<1>(blocks * 256, 256), [=](sycl::nd_item<1> it) [[sycl::reqd_sub_group_size(32)]] {
        const int row = it.get_group(0) * MV_ROWS + (it.get_local_id(0) >> 5);
        const int lane = it.get_local_id(0) & 31;
        if (row >= J.n_out) return;
        const block_q6_K* r = (const block_q6_K*) (J.w + (size_t) row * (J.n_in / 256) * 210);
        const int nb = J.n_in / 256;
        float s = 0.0f;
        for (int k = lane; k < nb * 32; k += 32) s += dot_q6_K(r + k / 32, J.x + (k / 32) * 8, k % 32);
        s = warp_sum(s);
        if (lane == 0) J.y[row] = s;
    });
}

// ---- V1/V2: the engine's cc-6.0 kernel (aligned words + shuffles, activation staged in SLM)
static inline uint32_t funnel_r(uint32_t lo, uint32_t hi, int sh) {
    return sh ? (lo >> sh) | (hi << (32 - sh)) : lo;
}
struct DecW14 { int vi[2], sc[2]; float d; };
static inline void q6_words(const uint8_t* s, int lane, uint32_t& w0, uint32_t& w1, int& sh) {
    sh = (int) ((uintptr_t) s & 3);
    const uint32_t* a = (const uint32_t*) (s - sh);
    w0 = (lane == 0 && sh) ? (uint32_t) (*(const uint16_t*) s) << 16 : a[lane];
    w1 = lane > 20 ? 0u : (lane == 20 && !sh) ? (uint32_t) *(const uint16_t*) (s + 208) : a[32 + lane];
}
static inline void q6_fields(DecW14& D, uint32_t w0, uint32_t w1, int sh, int lane) {
    auto sg = sycl::ext::oneapi::this_work_item::get_sub_group();
    const int f = 8 * sh;
    const uint32_t nx = sycl::select_from_group(sg, lane == 0 ? w1 : w0, (lane + 1) & 31);
    const int vl = (int) funnel_r(w0, nx, f);
    const int qi = 8 * (lane / 16) + lane % 8;
    const uint32_t h0 = sycl::select_from_group(sg, w1, qi), h1 = sycl::select_from_group(sg, w1, qi + 1);
    const int vh = (int) funnel_r(h0, h1, f) >> (2 * ((lane % 16) / 8));
    const int sb = 8 * (lane / 16) + (lane % 16) / 4 + sh;
    const uint32_t s0 = sycl::select_from_group(sg, w1, 16 + (sb >> 2)), s1 = sycl::select_from_group(sg, w1, 17 + (sb >> 2));
    D.sc[0] = (int) (int8_t) (s0 >> (8 * (sb & 3)));
    D.sc[1] = (int) (int8_t) (s1 >> (8 * (sb & 3)));
    const uint32_t dw = sycl::select_from_group(sg, w1, 20);
    D.d = (float) sycl::bit_cast<sycl::half>((uint16_t) (dw >> f));
#pragma unroll
    for (int i = 0; i < 2; ++i) {
        const int vil = (vl >> (4 * i)) & 0x0f0f0f0f;
        const int vih = ((vh >> (4 * i)) << 4) & 0x30303030;
        D.vi[i] = m32(vil | vih);
    }
}
template <int R>
static sycl::event vp100(sycl::queue& q, const Job& J) {
    const int per = MV_ROWS * R, blocks = (J.n_out + per - 1) / per;
    const size_t xs = (size_t) (J.n_in / 32) * sizeof(block_q8_1);
    return q.submit([&](sycl::handler& h) {
        sycl::local_accessor<int, 1> lx(sycl::range<1>(xs / 4), h);
        h.parallel_for(sycl::nd_range<1>(blocks * 256, 256), [=](sycl::nd_item<1> it) [[sycl::reqd_sub_group_size(32)]] {
            int* xsm = &lx[0];
            const int nw = (int) (xs / 4);
            for (int i = it.get_local_id(0); i < nw; i += 256) xsm[i] = ((const int*) J.x)[i];
            sycl::group_barrier(it.get_group());
            const block_q8_1* xq = (const block_q8_1*) xsm;
            const int row0 = (it.get_group(0) * MV_ROWS + (it.get_local_id(0) >> 5)) * R;
            const int lane = it.get_local_id(0) & 31;
            if (row0 >= J.n_out) return;
            const size_t rb = (size_t) (J.n_in / 256) * 210;
            const uint8_t* w[R];
#pragma unroll
            for (int r = 0; r < R; ++r) w[r] = J.w + (size_t) sycl::min(row0 + r, J.n_out - 1) * rb;
            float s[R];
#pragma unroll
            for (int r = 0; r < R; ++r) s[r] = 0.0f;
            const int nk = (J.n_in / 256) * 32;
            for (int k = lane; k < nk; k += 32) {
                const int kbx = k / 32, iqs = k % 32;
                uint32_t w0[R], w1[R];
                int sh[R];
#pragma unroll
                for (int r = 0; r < R; ++r) q6_words(w[r] + (size_t) kbx * 210, lane, w0[r], w1[r], sh[r]);
                DecW14 dw[R];
#pragma unroll
                for (int r = 0; r < R; ++r) q6_fields(dw[r], w0[r], w1[r], sh[r], lane);
                const block_q8_1* b = xq + kbx * 8;
                const int o = 4 * (iqs / 16) + (iqs % 16) / 8, qq = iqs % 8;
                int u[2]; float d8[2];
#pragma unroll
                for (int i = 0; i < 2; ++i) { u[i] = ((const int*) b[o + 2 * i].qs)[qq]; d8[i] = (float) b[o + 2 * i].ds[0]; }
#pragma unroll
                for (int r = 0; r < R; ++r) {
                    float sumf = 0.0f;
#pragma unroll
                    for (int i = 0; i < 2; ++i) sumf += d8[i] * (dp4a(dw[r].vi[i], u[i], 0) * dw[r].sc[i]);
                    s[r] += dw[r].d * sumf;
                }
            }
#pragma unroll
            for (int r = 0; r < R; ++r) {
                const float v = warp_sum(s[r]);
                if (lane == 0 && row0 + r < J.n_out) J.y[row0 + r] = v;
            }
        });
    });
}

// ---- V3/V4/V5: SoA (ql | qh | scales | d, each its own array, block-major per row) with production's per-lane calls
static inline float dot_soa(const uint8_t* ql, const uint8_t* qh, const int8_t* scs, float d, const int* u4,
                            const float* d8v, int iqs) {
    const int scale_offset = 8 * (iqs / 16) + (iqs % 16) / 4;
    const int vh_shift = 2 * ((iqs % 16) / 8);
    const int vl = ((const int*) ql)[iqs];
    const int vh = ((const int*) qh)[8 * (iqs / 16) + iqs % 8] >> vh_shift;
    float sumf = 0.0f;
#pragma unroll
    for (int i = 0; i < 2; ++i) {
        const int sc = scs[scale_offset + 4 * i];
        const int vil = (vl >> (4 * i)) & 0x0f0f0f0f;
        const int vih = ((vh >> (4 * i)) << 4) & 0x30303030;
        sumf += d8v[i] * (dp4a(m32(vil | vih), u4[i], 0) * sc);
    }
    return d * sumf;
}
template <bool SLM, int R>
static sycl::event vsoa(sycl::queue& q, const Job& J) {
    const int per = MV_ROWS * R, blocks = (J.n_out + per - 1) / per;
    const size_t xs = (size_t) (J.n_in / 32) * sizeof(block_q8_1);
    return q.submit([&](sycl::handler& h) {
        sycl::local_accessor<int, 1> lx(sycl::range<1>(SLM ? xs / 4 : 1), h);
        h.parallel_for(sycl::nd_range<1>(blocks * 256, 256), [=](sycl::nd_item<1> it) [[sycl::reqd_sub_group_size(32)]] {
            const block_q8_1* xq = J.x;
            if constexpr (SLM) {
                int* xsm = &lx[0];
                const int nw = (int) (xs / 4);
                for (int i = it.get_local_id(0); i < nw; i += 256) xsm[i] = ((const int*) J.x)[i];
                sycl::group_barrier(it.get_group());
                xq = (const block_q8_1*) xsm;
            }
            const int row0 = (it.get_group(0) * MV_ROWS + (it.get_local_id(0) >> 5)) * R;
            const int lane = it.get_local_id(0) & 31;
            if (row0 >= J.n_out) return;
            const int nb = J.n_in / 256;
            float s[R];
#pragma unroll
            for (int r = 0; r < R; ++r) s[r] = 0.0f;
            for (int k = lane; k < nb * 32; k += 32) {
                const int kbx = k / 32, iqs = k % 32;
                const block_q8_1* b = xq + kbx * 8;
                const int o = 4 * (iqs / 16) + (iqs % 16) / 8, qq = iqs % 8;
                int u[2]; float d8[2];
#pragma unroll
                for (int i = 0; i < 2; ++i) { u[i] = ((const int*) b[o + 2 * i].qs)[qq]; d8[i] = (float) b[o + 2 * i].ds[0]; }
#pragma unroll
                for (int r = 0; r < R; ++r) {
                    const size_t blk = (size_t) sycl::min(row0 + r, J.n_out - 1) * nb + kbx;
                    s[r] += dot_soa(J.ql + blk * 128, J.qh + blk * 64, J.sc + blk * 16, (float) J.d[blk], u, d8, iqs);
                }
            }
#pragma unroll
            for (int r = 0; r < R; ++r) {
                const float v = warp_sum(s[r]);
                if (lane == 0 && row0 + r < J.n_out) J.y[row0 + r] = v;
            }
        });
    });
}


// ---- V7/V8: AoS layout unchanged; a block is 4-aligned or 2 off (210 B blocks, even nb).  Each field's int read as
// aligned 32-bit words, funnel-shifted when the block is 2 off (uniform across the warp: one block an iteration).
static inline int ld_i32_al(const uint8_t* p, int sh) {   // the int at p (p 2-aligned), sh = p & 3 in {0, 2}
    const uint32_t* a = (const uint32_t*) (p - sh);
    if (sh == 0) return (int) a[0];
    return (int) ((a[0] >> 16) | (a[1] << 16));
}
template <int R, int WARPS>
static sycl::event vaos(sycl::queue& q, const Job& J) {
    const int per = WARPS * R, blocks = (J.n_out + per - 1) / per;
    return q.parallel_for(sycl::nd_range<1>(blocks * WARPS * 32, WARPS * 32), [=](sycl::nd_item<1> it) [[sycl::reqd_sub_group_size(32)]] {
        const int row0 = (it.get_group(0) * WARPS + (it.get_local_id(0) >> 5)) * R;
        const int lane = it.get_local_id(0) & 31;
        if (row0 >= J.n_out) return;
        const int nb = J.n_in / 256;
        float s[R];
#pragma unroll
        for (int r = 0; r < R; ++r) s[r] = 0.0f;
        for (int k = lane; k < nb * 32; k += 32) {
            const int kbx = k / 32, iqs = k % 32;
            const block_q8_1* b = J.x + kbx * 8;
            const int o = 4 * (iqs / 16) + (iqs % 16) / 8, qq = iqs % 8;
            int u[2]; float d8[2];
#pragma unroll
            for (int i = 0; i < 2; ++i) { u[i] = ((const int*) b[o + 2 * i].qs)[qq]; d8[i] = (float) b[o + 2 * i].ds[0]; }
            const int scale_offset = 8 * (iqs / 16) + (iqs % 16) / 4;
            const int vh_shift = 2 * ((iqs % 16) / 8);
#pragma unroll
            for (int r = 0; r < R; ++r) {
                const block_q6_K* w = (const block_q6_K*) (J.w + (size_t) sycl::min(row0 + r, J.n_out - 1) * nb * 210) + kbx;
                const int sh = (int) ((uintptr_t) w & 3);
                const int vl = ld_i32_al(w->ql + 4 * iqs, sh);
                const int vh = ld_i32_al(w->qh + 4 * (8 * (iqs / 16) + iqs % 8), sh) >> vh_shift;
                float sumf = 0.0f;
#pragma unroll
                for (int i = 0; i < 2; ++i) {
                    const int sc = w->scales[scale_offset + 4 * i];
                    const int vil = (vl >> (4 * i)) & 0x0f0f0f0f;
                    const int vih = ((vh >> (4 * i)) << 4) & 0x30303030;
                    sumf += d8[i] * (dp4a(m32(vil | vih), u[i], 0) * sc);
                }
                s[r] += (float) w->d * sumf;
            }
        }
#pragma unroll
        for (int r = 0; r < R; ++r) {
            const float v = warp_sum(s[r]);
            if (lane == 0 && row0 + r < J.n_out) J.y[row0 + r] = v;
        }
    });
}

struct Shape { const char* name; int n_out, n_in; };

int main(int argc, char** argv) {
    const int iters = argc > 1 ? std::atoi(argv[1]) : 200;
    const int only = argc > 2 ? std::atoi(argv[2]) : -1;
    sycl::queue q(sycl::gpu_selector_v, {sycl::property::queue::in_order(), sycl::property::queue::enable_profiling()});
    std::printf("device: %s\n", q.get_device().get_info<sycl::info::device::name>().c_str());
    const Shape shapes[] = {
        {"kda qkv 24576x4096", 24576, 4096}, {"kda one 8192x4096", 8192, 4096}, {"attn_out 4096x16384", 4096, 16384},
        {"q_b 16384x1536", 16384, 1536},     {"shexp gu 4096x4096", 4096, 4096}, {"shexp dn 4096x2048", 4096, 2048},
        {"q_a+kv_a 2048x4096", 2048, 4096},  {"ffn 12288x4096", 12288, 4096},    {"head 154880x4096", 154880, 4096},
    };
    const char* vname[] = {"V0 prod", "V1 p100 R2", "V2 p100 R4", "V3 soa", "V4 soa+slm", "V5 soa R2", "V6 soa+slm R2", "V7 aos-al R1", "V8 aos-al R2", "V9 aos-al R4", "V10 soa R4", "V11 aos-al R2 w4"};
    const int NV = 12;
    std::mt19937 rng(42);
    for (const Shape& S : shapes) {
        const int nb = S.n_in / 256;
        const size_t mbytes = (size_t) S.n_out * nb * 210;
        const int NP = std::max(1, (int) std::min<size_t>(64, (512ull << 20) / mbytes));   // >= 512 MB of copies (L2 ~18 MB)
        std::vector<uint8_t> h(mbytes);
        for (auto& v : h) v = (uint8_t) rng();
        for (size_t i = 0; i < (size_t) S.n_out * nb; ++i) {
            block_q6_K* b = (block_q6_K*) h.data() + i;
            b->d = sycl::half(0.0005f + 0.002f * (float) (rng() % 1000) / 1000.0f);
        }
        std::vector<block_q8_1> hx(S.n_in / 32);
        for (auto& b : hx) {
            for (int j = 0; j < 32; ++j) b.qs[j] = (int8_t) ((int) (rng() % 255) - 127);
            b.ds = sycl::half2(0.01f + 0.01f * (float) (rng() % 100) / 100.0f, 0.0f);
        }
        // SoA copy
        std::vector<uint8_t> hql((size_t) S.n_out * nb * 128), hqh((size_t) S.n_out * nb * 64);
        std::vector<int8_t> hsc((size_t) S.n_out * nb * 16);
        std::vector<sycl::half> hd((size_t) S.n_out * nb);
        for (size_t i = 0; i < (size_t) S.n_out * nb; ++i) {
            const block_q6_K* b = (const block_q6_K*) h.data() + i;
            std::memcpy(&hql[i * 128], b->ql, 128); std::memcpy(&hqh[i * 64], b->qh, 64);
            std::memcpy(&hsc[i * 16], b->scales, 16); hd[i] = b->d;
        }
        uint8_t* dw = sycl::malloc_device<uint8_t>(mbytes * NP, q);
        uint8_t* dql = sycl::malloc_device<uint8_t>(hql.size() * NP, q);
        uint8_t* dqh = sycl::malloc_device<uint8_t>(hqh.size() * NP, q);
        int8_t* dsc = sycl::malloc_device<int8_t>(hsc.size() * NP, q);
        sycl::half* dd = sycl::malloc_device<sycl::half>(hd.size() * NP, q);
        for (int p = 0; p < NP; ++p) {
            q.memcpy(dw + p * mbytes, h.data(), mbytes);
            q.memcpy(dql + p * hql.size(), hql.data(), hql.size());
            q.memcpy(dqh + p * hqh.size(), hqh.data(), hqh.size());
            q.memcpy(dsc + p * hsc.size(), hsc.data(), hsc.size());
            q.memcpy(dd + p * hd.size(), hd.data(), hd.size() * sizeof(sycl::half));
        }
        block_q8_1* dx = sycl::malloc_device<block_q8_1>(hx.size(), q);
        q.memcpy(dx, hx.data(), hx.size() * sizeof(block_q8_1));
        float* dy = sycl::malloc_device<float>((size_t) S.n_out * NV, q);
        q.wait();
        std::vector<float> ref(S.n_out), got(S.n_out);
        std::printf("== %s  (%.1f MB, %d cold copies)\n", S.name, mbytes / 1e6, NP);
        for (int v = 0; v < NV; ++v) {
            if (only >= 0 && v < only && v != 0) continue;
            auto launch = [&](int p) -> sycl::event {
                Job J{dw + p * mbytes, dx, dy + (size_t) v * S.n_out, S.n_in, S.n_out,
                      dql + p * hql.size(), dqh + p * hqh.size(), dsc + p * hsc.size(), dd + p * hd.size()};
                switch (v) {
                    case 0: return v0(q, J);
                    case 1: return vp100<2>(q, J);
                    case 2: return vp100<4>(q, J);
                    case 3: return vsoa<false, 1>(q, J);
                    case 4: return vsoa<true, 1>(q, J);
                    case 5: return vsoa<false, 2>(q, J);
                    case 6: return vsoa<true, 2>(q, J);
                    case 7: return vaos<1, 8>(q, J);
                    case 8: return vaos<2, 8>(q, J);
                    case 9: return vaos<4, 8>(q, J);
                    case 10: return vsoa<false, 4>(q, J);
                    default: return vaos<2, 4>(q, J);
                }
            };
            for (int i = 0; i < 20; ++i) launch(i % NP);
            q.wait();
            std::vector<double> us;
            for (int i = 0; i < iters; ++i) {
                sycl::event e = launch(i % NP);
                e.wait();
                const double t = (e.get_profiling_info<sycl::info::event_profiling::command_end>() -
                                  e.get_profiling_info<sycl::info::event_profiling::command_start>()) * 1e-3;
                us.push_back(t);
            }
            std::sort(us.begin(), us.end());
            const double med = us[us.size() / 2];
            q.memcpy(got.data(), dy + (size_t) v * S.n_out, S.n_out * sizeof(float)).wait();
            if (v == 0) ref = got;
            double md = 0, mref = 0; int exact = 0;
            for (int i = 0; i < S.n_out; ++i) {
                md = std::max(md, (double) std::fabs(got[i] - ref[i]));
                mref = std::max(mref, (double) std::fabs(ref[i]));
                exact += std::memcmp(&got[i], &ref[i], 4) == 0;
            }
            std::printf("   %-14s %8.1f us  %6.1f GB/s  bit-exact %d/%d  max|d| %.3g (max|y| %.3g)\n", vname[v], med,
                        mbytes / (med * 1e3), exact, S.n_out, md, mref);
        }
        sycl::free(dw, q); sycl::free(dql, q); sycl::free(dqh, q); sycl::free(dsc, q); sycl::free(dd, q);
        sycl::free(dx, q); sycl::free(dy, q);
    }
    return 0;
}
