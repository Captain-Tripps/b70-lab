// gu2.cpp - IQ2_S MoE expert gate/up (GLM-5.3 Maya-M decode: k = 8, n_embd 4096, n_ff 2048) - the LIVE kernel's
// structure (grid (n_ff / 32 chunks, k), 32 rows a work-group, fixups16 sign bits, 8 KB iq2s_grid in SLM, native
// dp4a) against codebook / geometry variants.  Bit-exact check of every exact variant against the live replica,
// the replica against a CPU reference, GPU time per launch from profiling events with experts rotated through a
// 48-expert pool (258 MB, far over L2) so weights come from DRAM.
//
// Build: icpx -fsycl -O3 -std=c++17 -DNOMINMAX gu2.cpp -o gu2.exe   (JIT)
// Run:   ONEAPI_DEVICE_SELECTOR=level_zero:N gu2.exe [iters=400]
//
// Variant knobs (template): TAB  0 = u64 table in SLM (live), 1 = 2 KB u16 code table in SLM, 2 = u16 code table
//                                read from global (L1), 3 = u64 table split into lo/hi u32 planes in SLM,
//                                9 = no lookup (diagnostic, wrong results)
//                           RPW  gate rows (= up rows) a sub-group: 2 (live, 16 sub-groups) or 4 (8 sub-groups)
//                           CPW  32-row chunks a work-group walks (table load amortized over CPW chunks)
// The u16 code: every iq2s_grid byte is 8, 25 or 43.  Bit j of the low byte = (byte j >= 25), bit j of the high
// byte = (byte j == 43); byte j = 8 + 17 * b0 + 18 * b1 - rebuilt 4 bytes at a time with the same multiply spread
// fixups16 uses for the signs.  Integer-identical to the table, so the float results are bit-identical.
#include "common.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <functional>
#include <random>
#include <vector>

namespace gu2 {

constexpr int ROWS = 32;   // rows a chunk (one q8_1 block of h in the engine)

struct XV { int u[8]; float d; };

inline XV load_xv(const block_q8_1* xb) {
    XV v;
    const int* q = (const int*) xb->qs;
#pragma unroll
    for (int i = 0; i < 8; ++i) v.u[i] = q[i];
    v.d = (float) xb->ds.x();
    return v;
}

inline uint32_t spread4(uint32_t nib) { return ((nib * 0x00204081u) & 0x01010101u); }
// the same 4 bits -> 4 bytes with no 32x32 multiply (Xe2 emulates those as mul + mach + macl): 0x204081 =
// 0x4081 (a 16-bit constant, one native mul) + 1 << 21
inline uint32_t spread4f(uint32_t nib) { return ((nib * 0x4081u) + (nib << 21)) & 0x01010101u; }

template <int TAB, bool FAST = false>
inline void grid8(int idx, const uint32_t* tab, uint32_t& lo, uint32_t& hi) {
    if constexpr (TAB == 0) {
        const sycl::uint2 g = ((const sycl::uint2*) tab)[idx];
        lo = g.x();
        hi = g.y();
    } else if constexpr (TAB == 1 || TAB == 2) {
        const uint32_t c = ((const uint16_t*) tab)[idx];
        if constexpr (FAST) {
            lo = 0x08080808u + 17u * spread4f(c & 0xFu) + 18u * spread4f((c >> 8) & 0xFu);
            hi = 0x08080808u + 17u * spread4f((c >> 4) & 0xFu) + 18u * spread4f(c >> 12);
        } else {
            lo = 0x08080808u + 17u * spread4(c & 0xFu) + 18u * spread4((c >> 8) & 0xFu);
            hi = 0x08080808u + 17u * spread4((c >> 4) & 0xFu) + 18u * spread4(c >> 12);
        }
    } else if constexpr (TAB == 3) {
        lo = tab[idx];
        hi = tab[1024 + idx];
    } else {
        lo = 0x08080808u + ((uint32_t) idx & 0x07070707u);
        hi = 0x08080808u + (((uint32_t) idx >> 3) & 0x07070707u);
    }
}

template <int TAB>
inline float dw_iq2s(const uint8_t* row, int kbx, int iqs, const XV& x, const uint32_t* tab) {
    const block_iq2_s* bq2 = (const block_iq2_s*) row + kbx;
    const int qs_packed = get_int_b2(bq2->qs, iqs / 2);
    const uint8_t* qs = (const uint8_t*) &qs_packed;
    const int qh = bq2->qh[iqs / 2];
    const int signs_packed_32 = get_int_b2(bq2->qs, QK_K / 32 + iqs / 2);
    const uint8_t* s8 = (const uint8_t*) &signs_packed_32;
    const int ls0 = bq2->scales[iqs / 2] & 0x0F, ls1 = bq2->scales[iqs / 2] >> 4;
    int sumi0 = 0, sumi1 = 0;
#pragma unroll
    for (int l0 = 0; l0 < 8; l0 += 2) {
        uint32_t glo, ghi;
        grid8<TAB>(qs[l0 / 2] | ((qh << (8 - l0)) & 0x300), tab, glo, ghi);
        const uint32_t sgm = s8[l0 / 2];
        const uint32_t sm0 = (((sgm & 0x0Fu) * 0x00204081u) & 0x01010101u) * 0xFFu;
        const uint32_t sm1 = ((((sgm >> 4) & 0x0Fu) * 0x00204081u) & 0x01010101u) * 0xFFu;
        const int gl = (int) ((glo ^ sm0) + (sm0 & 0x01010101u));
        const int gh = (int) ((ghi ^ sm1) + (sm1 & 0x01010101u));
        if (l0 < 4) {
            sumi0 = dp4a(gl, x.u[l0 + 0], sumi0);
            sumi0 = dp4a(gh, x.u[l0 + 1], sumi0);
        } else {
            sumi1 = dp4a(gl, x.u[l0 + 0], sumi1);
            sumi1 = dp4a(gh, x.u[l0 + 1], sumi1);
        }
    }
    const int sumi = (sumi0 * ls0 + sumi1 * ls1 + (sumi0 + sumi1) / 2) / 4;
    return h2f(bq2->d) * x.d * sumi;
}

constexpr int tab_words(int TAB) { return TAB == 0 || TAB == 3 ? 2048 : TAB == 1 ? 512 : 1; }

template <int TAB, int RPW, int CPW>
void launch(sycl::queue& q, const GuArgs& a, const uint32_t* tab_g) {
    constexpr int NW = ROWS / RPW, NR = 2 * RPW, TW = tab_words(TAB);
    const int chunks = a.n_ff / ROWS;
    const size_t rb = (size_t) (a.n_embd / QK_K) * sizeof(block_iq2_s);
    q.submit([&](sycl::handler& h) {
        sycl::local_accessor<uint32_t, 1> s_tab(sycl::range<1>(TW), h);
        const GuArgs A = a;
        h.parallel_for(sycl::nd_range<2>(sycl::range<2>(A.k, (chunks / CPW) * NW * 32), sycl::range<2>(1, NW * 32)),
                       [=](sycl::nd_item<2> it) [[sycl::reqd_sub_group_size(32)]] {
            const int ei = (int) it.get_group(0), tid = (int) it.get_local_id(1), lane = tid & 31, warp = tid >> 5;
            const uint32_t* tab = tab_g;
            if constexpr (TAB != 2 && TAB != 9) {
                for (int i = tid; i < TW; i += NW * 32) s_tab[i] = tab_g[i];
                sycl::group_barrier(it.get_group());
                tab = &s_tab[0];
            }
            const uint8_t* blob = (const uint8_t*) A.plan[ei];
            const int nb = A.n_embd / QK_K;
            const auto sg = it.get_sub_group();
            for (int c = 0; c < CPW; ++c) {
                const int chunk = (int) it.get_group(1) * CPW + c;
                const uint8_t* rows[NR];
#pragma unroll
                for (int j = 0; j < RPW; ++j) {
                    const int r = chunk * ROWS + warp * RPW + j;
                    rows[j] = blob + (size_t) r * rb;
                    rows[RPW + j] = blob + (size_t) A.n_ff * rb + (size_t) r * rb;
                }
                float acc[NR];
#pragma unroll
                for (int j = 0; j < NR; ++j) acc[j] = 0.0f;
                for (int k = lane; k < nb * 8; k += 32) {
                    const int kbx = k / 8, ki = k % 8;
                    const XV xv = load_xv(A.x + kbx * 8 + ki);
#pragma unroll
                    for (int j = 0; j < NR; ++j) acc[j] += dw_iq2s<TAB>(rows[j], kbx, 2 * ki, xv, tab);
                }
#pragma unroll
                for (int j = 0; j < NR; ++j) acc[j] = sycl::reduce_over_group(sg, acc[j], sycl::plus<float>());
                if (lane == 0) {
#pragma unroll
                    for (int j = 0; j < RPW; ++j) {
                        const int r = chunk * ROWS + warp * RPW + j;
                        A.g[(size_t) ei * A.n_ff + r] = acc[j];
                        A.u[(size_t) ei * A.n_ff + r] = acc[RPW + j];
                    }
                }
            }
        });
    });
}

// ---- AL: the same bytes through aligned 32-bit loads.  The live dw reads each row's sub-block as 7 gathers
// (qs and signs as two u16 halves each - IQ2_S blocks are 82 bytes, so half of them start 2 bytes off a word -
// plus qh, scales and d), each behind a 64-bit (row + kbx * 82) pointer product.  Here one 32-bit in-row offset
// a lane serves every row (the rows of a step share it), and per row: qs = 2 words, signs = 2 words, qh + scales
// = 3 words, d = 2 words, each pair funnel-shifted by the address's byte phase (any blob alignment).  Same bytes,
// same integer math -> bit-identical.
inline uint32_t fsh(uint32_t lo, uint32_t hi, uint32_t s8) {   // bytes [ph, ph + 4) of hi:lo, s8 = 8 * ph
    return (lo >> s8) | ((hi << 1) << (31 - s8));
}

template <int TAB, bool FAST = false>
inline float dw_al(const uint8_t* row, uint32_t off, int ki, const XV& x, const uint32_t* tab) {
    const uintptr_t a_qs = (uintptr_t) row + off + 2 + 4 * ki;      // qs[4ki .. 4ki + 3]
    const uintptr_t a_sg = a_qs + 32;                               // qs[32 + 4ki ..] (signs)
    const uintptr_t a_hs = (uintptr_t) row + off + 66 + ki;         // qh[ki], scales[ki] at +8
    const uintptr_t a_d = (uintptr_t) row + off;                    // d
    const uint32_t* p_qs = (const uint32_t*) (a_qs & ~(uintptr_t) 3);
    const uint32_t* p_sg = (const uint32_t*) (a_sg & ~(uintptr_t) 3);
    const uint32_t* p_hs = (const uint32_t*) (a_hs & ~(uintptr_t) 3);
    const uint32_t* p_d = (const uint32_t*) (a_d & ~(uintptr_t) 3);
    const uint32_t s_q = 8u * (uint32_t) (a_qs & 3), s_h = 8u * (uint32_t) (a_hs & 3), s_d = 8u * (uint32_t) (a_d & 3);
    const uint32_t qs_packed = fsh(p_qs[0], p_qs[1], s_q);
    const uint32_t signs_packed = fsh(p_sg[0], p_sg[1], s_q);   // same phase: 32 bytes on
    const uint32_t qh = (p_hs[0] >> s_h) & 0xFFu;
    const uint32_t sc = (p_hs[2] >> s_h) & 0xFFu;                  // byte ph + 8 lies in word 2
    const uint16_t dh = (uint16_t) (fsh(p_d[0], p_d[1], s_d) & 0xFFFFu);
    const int ls0 = (int) (sc & 0x0F), ls1 = (int) (sc >> 4);
    int sumi0 = 0, sumi1 = 0;
#pragma unroll
    for (int l0 = 0; l0 < 8; l0 += 2) {
        uint32_t glo, ghi;
        grid8<TAB, FAST>((int) (((qs_packed >> (4 * l0)) & 0xFFu) | ((qh << (8 - l0)) & 0x300u)), tab, glo, ghi);
        const uint32_t sgm = (signs_packed >> (4 * l0)) & 0xFFu;
        int gl, gh;
        if constexpr (FAST) {
            const uint32_t p0 = spread4f(sgm & 0x0Fu), p1 = spread4f(sgm >> 4);
            gl = (int) ((glo ^ ((p0 << 8) - p0)) + p0);
            gh = (int) ((ghi ^ ((p1 << 8) - p1)) + p1);
        } else {
            const uint32_t sm0 = (((sgm & 0x0Fu) * 0x00204081u) & 0x01010101u) * 0xFFu;
            const uint32_t sm1 = ((((sgm >> 4) & 0x0Fu) * 0x00204081u) & 0x01010101u) * 0xFFu;
            gl = (int) ((glo ^ sm0) + (sm0 & 0x01010101u));
            gh = (int) ((ghi ^ sm1) + (sm1 & 0x01010101u));
        }
        if (l0 < 4) {
            sumi0 = dp4a(gl, x.u[l0 + 0], sumi0);
            sumi0 = dp4a(gh, x.u[l0 + 1], sumi0);
        } else {
            sumi1 = dp4a(gl, x.u[l0 + 0], sumi1);
            sumi1 = dp4a(gh, x.u[l0 + 1], sumi1);
        }
    }
    const int sumi = (sumi0 * ls0 + sumi1 * ls1 + (sumi0 + sumi1) / 2) / 4;
    return h2f(dh) * x.d * sumi;
}

template <int TAB, int RPW, bool FAST = false>
void launch_al(sycl::queue& q, const GuArgs& a, const uint32_t* tab_g) {
    constexpr int NW = ROWS / RPW, NR = 2 * RPW, TW = tab_words(TAB);
    const int chunks = a.n_ff / ROWS;
    const uint32_t rb = (uint32_t) (a.n_embd / QK_K) * (uint32_t) sizeof(block_iq2_s);
    q.submit([&](sycl::handler& h) {
        sycl::local_accessor<uint32_t, 1> s_tab(sycl::range<1>(TW), h);
        const GuArgs A = a;
        h.parallel_for(sycl::nd_range<2>(sycl::range<2>(A.k, chunks * NW * 32), sycl::range<2>(1, NW * 32)),
                       [=](sycl::nd_item<2> it) [[sycl::reqd_sub_group_size(32)]] {
            const int ei = (int) it.get_group(0), chunk = (int) it.get_group(1), tid = (int) it.get_local_id(1),
                      lane = tid & 31, warp = tid >> 5;
            const uint32_t* tab = tab_g;
            if constexpr (TAB != 2 && TAB != 9) {
                for (int i = tid; i < TW; i += NW * 32) s_tab[i] = tab_g[i];
                sycl::group_barrier(it.get_group());
                tab = &s_tab[0];
            }
            const uint8_t* blob = (const uint8_t*) A.plan[ei];
            const int nb = A.n_embd / QK_K;
            const uint8_t* rows[NR];
#pragma unroll
            for (int j = 0; j < RPW; ++j) {
                const int r = chunk * ROWS + warp * RPW + j;
                rows[j] = blob + (size_t) r * rb;
                rows[RPW + j] = blob + (size_t) A.n_ff * rb + (size_t) r * rb;
            }
            float acc[NR];
#pragma unroll
            for (int j = 0; j < NR; ++j) acc[j] = 0.0f;
            for (int k = lane; k < nb * 8; k += 32) {
                const int kbx = k >> 3, ki = k & 7;
                const uint32_t off = (uint32_t) kbx * 82u;
                const XV xv = load_xv(A.x + k);
#pragma unroll
                for (int j = 0; j < NR; ++j) acc[j] += dw_al<TAB, FAST>(rows[j], off, ki, xv, tab);
            }
            const auto sg = it.get_sub_group();
#pragma unroll
            for (int j = 0; j < NR; ++j) acc[j] = sycl::reduce_over_group(sg, acc[j], sycl::plus<float>());
            if (lane == 0) {
#pragma unroll
                for (int j = 0; j < RPW; ++j) {
                    const int r = chunk * ROWS + warp * RPW + j;
                    A.g[(size_t) ei * A.n_ff + r] = acc[j];
                    A.u[(size_t) ei * A.n_ff + r] = acc[RPW + j];
                }
            }
        });
    });
}

// ---- IMM: the live structure and bytes, but addresses built once a step: per lane three bases into the first gate
// row (block start, block + 4ki, block + ki) and three into the first up row; every load is base + a constant (the
// next row is +rb bytes, each field a fixed offset), not a fresh 64-bit (row + kbx * 82 + field) product per load.
// Same bytes, same integer and float math, same per-lane accumulation order -> bit-identical.
template <int TAB>
inline float dw_imm(const uint8_t* b0, const uint8_t* b4, const uint8_t* b1, const XV& x, const uint32_t* tab) {
    const uint32_t qs_packed = (uint32_t) *(const uint16_t*) (b4 + 2) | ((uint32_t) *(const uint16_t*) (b4 + 4) << 16);
    const uint32_t signs_packed = (uint32_t) *(const uint16_t*) (b4 + 34) | ((uint32_t) *(const uint16_t*) (b4 + 36) << 16);
    const uint32_t qh = b1[66], sc = b1[74];
    const uint16_t dh = *(const uint16_t*) b0;
    const int ls0 = (int) (sc & 0x0F), ls1 = (int) (sc >> 4);
    int sumi0 = 0, sumi1 = 0;
#pragma unroll
    for (int l0 = 0; l0 < 8; l0 += 2) {
        uint32_t glo, ghi;
        grid8<TAB>((int) (((qs_packed >> (4 * l0)) & 0xFFu) | ((qh << (8 - l0)) & 0x300u)), tab, glo, ghi);
        const uint32_t sgm = (signs_packed >> (4 * l0)) & 0xFFu;
        const uint32_t p0 = spread4f(sgm & 0x0Fu), p1 = spread4f(sgm >> 4);
        const int gl = (int) ((glo ^ ((p0 << 8) - p0)) + p0);
        const int gh = (int) ((ghi ^ ((p1 << 8) - p1)) + p1);
        if (l0 < 4) {
            sumi0 = dp4a(gl, x.u[l0 + 0], sumi0);
            sumi0 = dp4a(gh, x.u[l0 + 1], sumi0);
        } else {
            sumi1 = dp4a(gl, x.u[l0 + 0], sumi1);
            sumi1 = dp4a(gh, x.u[l0 + 1], sumi1);
        }
    }
    const int sumi = (sumi0 * ls0 + sumi1 * ls1 + (sumi0 + sumi1) / 2) / 4;
    return h2f(dh) * x.d * sumi;
}

template <int TAB, int RPW>
void launch_imm(sycl::queue& q, const GuArgs& a, const uint32_t* tab_g) {
    constexpr int NW = ROWS / RPW, TW = tab_words(TAB);
    constexpr uint32_t RB = 16 * 82;   // n_embd 4096: the bench's (and the model's) row bytes, a compile-time stride
    const int chunks = a.n_ff / ROWS;
    q.submit([&](sycl::handler& h) {
        sycl::local_accessor<uint32_t, 1> s_tab(sycl::range<1>(TW), h);
        const GuArgs A = a;
        h.parallel_for(sycl::nd_range<2>(sycl::range<2>(A.k, chunks * NW * 32), sycl::range<2>(1, NW * 32)),
                       [=](sycl::nd_item<2> it) [[sycl::reqd_sub_group_size(32)]] {
            const int ei = (int) it.get_group(0), chunk = (int) it.get_group(1), tid = (int) it.get_local_id(1),
                      lane = tid & 31, warp = tid >> 5;
            const uint32_t* tab = tab_g;
            if constexpr (TAB != 2 && TAB != 9) {
                for (int i = tid; i < TW; i += NW * 32) s_tab[i] = tab_g[i];
                sycl::group_barrier(it.get_group());
                tab = &s_tab[0];
            }
            const uint8_t* blob = (const uint8_t*) A.plan[ei];
            const int r0 = chunk * ROWS + warp * RPW;
            const uint8_t* g0 = blob + (size_t) r0 * RB;
            const uint8_t* u0 = blob + (size_t) A.n_ff * RB + (size_t) r0 * RB;
            float ag[RPW], au[RPW];
#pragma unroll
            for (int j = 0; j < RPW; ++j) ag[j] = au[j] = 0.0f;
#pragma unroll
            for (int it4 = 0; it4 < 4; ++it4) {   // n_embd 4096: 128 sub-blocks, 4 a lane
                const int k = lane + 32 * it4, kbx = k >> 3, ki = k & 7;
                const uint32_t ob = (uint32_t) kbx * 82u;
                const XV xv = load_xv(A.x + k);
                const uint8_t *gb0 = g0 + ob, *gb4 = gb0 + 4 * ki, *gb1 = gb0 + ki;
                const uint8_t *ub0 = u0 + ob, *ub4 = ub0 + 4 * ki, *ub1 = ub0 + ki;
#pragma unroll
                for (int j = 0; j < RPW; ++j)
                    ag[j] += dw_imm<TAB>(gb0 + j * RB, gb4 + j * RB, gb1 + j * RB, xv, tab);
#pragma unroll
                for (int j = 0; j < RPW; ++j)
                    au[j] += dw_imm<TAB>(ub0 + j * RB, ub4 + j * RB, ub1 + j * RB, xv, tab);
            }
            const auto sg = it.get_sub_group();
#pragma unroll
            for (int j = 0; j < RPW; ++j) {
                ag[j] = sycl::reduce_over_group(sg, ag[j], sycl::plus<float>());
                au[j] = sycl::reduce_over_group(sg, au[j], sycl::plus<float>());
            }
            if (lane == 0) {
#pragma unroll
                for (int j = 0; j < RPW; ++j) {
                    A.g[(size_t) ei * A.n_ff + r0 + j] = ag[j];
                    A.u[(size_t) ei * A.n_ff + r0 + j] = au[j];
                }
            }
        });
    });
}

// ---- RPL: one ROW a lane.  All lanes of a sub-group sit on the same block index, so the activation is uniform
// (scalar loads, broadcast operands) and each lane reads its row's block PAIR (2 x 82 = 164 bytes = 41 aligned
// words when the row starts 4-aligned) with wide loads off one address.  No cross-lane reduction.  KS splits K
// (blocks) across sub-groups of a work-group for occupancy; partials combined in K order through SLM.
// Float accumulation order differs from the live kernel (sequential over sub-blocks instead of lane-strided +
// tree), so NOT bit-exact: the bench reports the max relative difference instead.
template <int OFF>
inline uint32_t w32(const uint32_t (&q)[41]) {
    if constexpr (OFF % 4 == 0) return q[OFF / 4];
    else return (q[OFF / 4] >> (8 * (OFF % 4))) | (q[OFF / 4 + 1] << (32 - 8 * (OFF % 4)));
}
template <int OFF>
inline uint32_t w8(const uint32_t (&q)[41]) { return (q[OFF / 4] >> (8 * (OFF % 4))) & 0xFFu; }

template <int B, int KI>
inline float sub_rpl(const uint32_t (&q)[41], const block_q8_1* xb, const uint32_t* tab) {
    const uint32_t qs_packed = w32<B + 2 + 4 * KI>(q);
    const uint32_t signs_packed = w32<B + 34 + 4 * KI>(q);
    const uint32_t qh = w8<B + 66 + KI>(q);
    const uint32_t sc = w8<B + 74 + KI>(q);
    const uint16_t dh = (uint16_t) (w32<B>(q) & 0xFFFFu);
    const int* xu = (const int*) xb->qs;
    const int ls0 = (int) (sc & 0x0F), ls1 = (int) (sc >> 4);
    int sumi0 = 0, sumi1 = 0;
#pragma unroll
    for (int l0 = 0; l0 < 8; l0 += 2) {
        const sycl::uint2 g = ((const sycl::uint2*) tab)[((qs_packed >> (4 * l0)) & 0xFFu) | ((qh << (8 - l0)) & 0x300u)];
        const uint32_t sgm = (signs_packed >> (4 * l0)) & 0xFFu;
        const uint32_t p0 = spread4f(sgm & 0x0Fu), p1 = spread4f(sgm >> 4);
        const int gl = (int) ((g.x() ^ ((p0 << 8) - p0)) + p0);
        const int gh = (int) ((g.y() ^ ((p1 << 8) - p1)) + p1);
        if (l0 < 4) {
            sumi0 = dp4a(gl, xu[l0 + 0], sumi0);
            sumi0 = dp4a(gh, xu[l0 + 1], sumi0);
        } else {
            sumi1 = dp4a(gl, xu[l0 + 0], sumi1);
            sumi1 = dp4a(gh, xu[l0 + 1], sumi1);
        }
    }
    const int sumi = (sumi0 * ls0 + sumi1 * ls1 + (sumi0 + sumi1) / 2) / 4;
    return h2f(dh) * (float) xb->ds.x() * sumi;
}

template <int B>
inline float block_rpl(const uint32_t (&q)[41], const block_q8_1* xb, const uint32_t* tab) {
    float s = 0.0f;
    s += sub_rpl<B, 0>(q, xb + 0, tab);
    s += sub_rpl<B, 1>(q, xb + 1, tab);
    s += sub_rpl<B, 2>(q, xb + 2, tab);
    s += sub_rpl<B, 3>(q, xb + 3, tab);
    s += sub_rpl<B, 4>(q, xb + 4, tab);
    s += sub_rpl<B, 5>(q, xb + 5, tab);
    s += sub_rpl<B, 6>(q, xb + 6, tab);
    s += sub_rpl<B, 7>(q, xb + 7, tab);
    return s;
}

template <int SG, int KS>
void launch_rpl(sycl::queue& q, const GuArgs& a, const uint32_t* tab_g) {
    constexpr int NSG = 8, RG = NSG / KS, WR = SG * RG;   // 8 sub-groups: RG row groups x KS K-splits
    const uint32_t rb = (uint32_t) (a.n_embd / QK_K) * (uint32_t) sizeof(block_iq2_s);
    q.submit([&](sycl::handler& h) {
        sycl::local_accessor<uint32_t, 1> s_tab(sycl::range<1>(2048), h);
        sycl::local_accessor<float, 1> s_g(sycl::range<1>(KS * WR), h), s_u(sycl::range<1>(KS * WR), h);
        const GuArgs A = a;
        h.parallel_for(sycl::nd_range<2>(sycl::range<2>(A.k, (A.n_ff / WR) * NSG * SG), sycl::range<2>(1, NSG * SG)),
                       [=](sycl::nd_item<2> it) [[sycl::reqd_sub_group_size(SG)]] {
            const int ei = (int) it.get_group(0), tid = (int) it.get_local_id(1);
            const int lane = tid % SG, sgi = tid / SG, rgi = sgi % RG, ksi = sgi / RG;
            for (int i = tid; i < 2048; i += NSG * SG) s_tab[i] = tab_g[i];
            sycl::group_barrier(it.get_group());
            const uint32_t* tab = &s_tab[0];
            const int r = (int) it.get_group(1) * WR + rgi * SG + lane;
            const uint8_t* blob = (const uint8_t*) A.plan[ei];
            const uint8_t* rg_ = blob + (size_t) r * rb;
            const uint8_t* ru_ = blob + (size_t) A.n_ff * rb + (size_t) r * rb;
            const int nb = A.n_embd / QK_K, per = nb / KS, kb0 = ksi * per;
            float ag = 0.0f, au = 0.0f;
            for (int kb = kb0; kb < kb0 + per; kb += 2) {
                const block_q8_1* xb = A.x + kb * 8;
                uint32_t qw[41];
                const uint32_t* pg = (const uint32_t*) (rg_ + (size_t) kb * 82);
#pragma unroll
                for (int i = 0; i < 41; ++i) qw[i] = pg[i];
                ag += block_rpl<0>(qw, xb, tab);
                ag += block_rpl<82>(qw, xb + 8, tab);
                const uint32_t* pu = (const uint32_t*) (ru_ + (size_t) kb * 82);
#pragma unroll
                for (int i = 0; i < 41; ++i) qw[i] = pu[i];
                au += block_rpl<0>(qw, xb, tab);
                au += block_rpl<82>(qw, xb + 8, tab);
            }
            if constexpr (KS == 1) {
                A.g[(size_t) ei * A.n_ff + r] = ag;
                A.u[(size_t) ei * A.n_ff + r] = au;
            } else {
                const int lr = rgi * SG + lane;
                s_g[ksi * WR + lr] = ag;
                s_u[ksi * WR + lr] = au;
                sycl::group_barrier(it.get_group());
                if (ksi == 0) {
                    float g = s_g[lr], u = s_u[lr];
#pragma unroll
                    for (int s = 1; s < KS; ++s) { g += s_g[s * WR + lr]; u += s_u[s * WR + lr]; }
                    A.g[(size_t) ei * A.n_ff + r] = g;
                    A.u[(size_t) ei * A.n_ff + r] = u;
                }
            }
        });
    });
}

// read-bandwidth floor: the same rows (gate + up of each chunk) read once with 16-byte loads, nothing else
void launch_peak(sycl::queue& q, const GuArgs& a) {
    const int chunks = a.n_ff / ROWS;
    const size_t rb = (size_t) (a.n_embd / QK_K) * sizeof(block_iq2_s);
    q.submit([&](sycl::handler& h) {
        const GuArgs A = a;
        h.parallel_for(sycl::nd_range<2>(sycl::range<2>(A.k, chunks * 512), sycl::range<2>(1, 512)),
                       [=](sycl::nd_item<2> it) [[sycl::reqd_sub_group_size(32)]] {
            const int ei = (int) it.get_group(0), chunk = (int) it.get_group(1), tid = (int) it.get_local_id(1);
            const uint8_t* blob = (const uint8_t*) A.plan[ei];
            const size_t span = (size_t) ROWS * rb / 16;   // uint4s in 32 rows (contiguous)
            const sycl::uint4* g4 = (const sycl::uint4*) (blob + (size_t) chunk * ROWS * rb);
            const sycl::uint4* u4 = (const sycl::uint4*) (blob + (size_t) A.n_ff * rb + (size_t) chunk * ROWS * rb);
            uint32_t s = 0;
            for (size_t i = tid; i < span; i += 512) {
                const sycl::uint4 v = g4[i], w = u4[i];
                s ^= v.x() ^ v.y() ^ v.z() ^ v.w() ^ w.x() ^ w.y() ^ w.z() ^ w.w();
            }
            if (s == 0x9e3779b9u) A.g[0] = 1.0f;   // keeps the loads
        });
    });
}

}  // namespace gu2

static void ref_dequant_iq2s(const block_iq2_s* b, int n, float* y) {
    static const uint8_t kmask[8] = {1, 2, 4, 8, 16, 32, 64, 128};
    for (int i = 0; i < n / QK_K; ++i) {
        const float d = h2f(b[i].d);
        const uint8_t* qs = b[i].qs;
        const uint8_t* signs = qs + QK_K / 8;
        for (int ib32 = 0; ib32 < QK_K / 32; ++ib32) {
            const float db[2] = {d * (0.5f + (b[i].scales[ib32] & 0xf)) * 0.25f,
                                 d * (0.5f + (b[i].scales[ib32] >> 4)) * 0.25f};
            for (int l = 0; l < 4; ++l) {
                const float dl = db[l / 2];
                const uint8_t* grid = (const uint8_t*) (h_iq2s_grid + (qs[l] | (b[i].qh[ib32] << (8 - 2 * l) & 0x300)));
                for (int j = 0; j < 8; ++j) *y++ = dl * grid[j] * (signs[l] & kmask[j] ? -1.f : 1.f);
            }
            qs += 4;
            signs += 4;
        }
    }
}

int main(int argc, char** argv) {
    const int K = 8, E = 4096, FF = 2048, NE = 48, NPLAN = 64;
    const int iters = argc > 1 ? std::atoi(argv[1]) : 400;
    const size_t rb = (size_t) (E / QK_K) * sizeof(block_iq2_s), blob = 2 * (size_t) FF * rb;
    sycl::queue q(sycl::gpu_selector_v, {sycl::property::queue::in_order(), sycl::property::queue::enable_profiling()});
    std::printf("device: %s\n", q.get_device().get_info<sycl::info::device::name>().c_str());
    if (q.get_device().has(sycl::aspect::ext_intel_pci_address))
        std::printf("pci: %s\n", q.get_device().get_info<sycl::ext::intel::info::device::pci_address>().c_str());

    // the 2 KB code table, checked against the grid while it is built
    std::vector<uint32_t> h_tab16(512, 0u), h_tab_split(2048);
    for (int e = 0; e < 1024; ++e) {
        uint32_t p0 = 0, p1 = 0;
        for (int j = 0; j < 8; ++j) {
            const uint32_t b = (uint32_t) (h_iq2s_grid[e] >> (8 * j)) & 0xFFu;
            if (b != 8 && b != 25 && b != 43) { std::printf("grid byte %u not in {8,25,43}\n", b); return 2; }
            p0 |= (uint32_t) (b >= 25) << j;
            p1 |= (uint32_t) (b == 43) << j;
        }
        ((uint16_t*) h_tab16.data())[e] = (uint16_t) (p0 | p1 << 8);
        h_tab_split[e] = (uint32_t) h_iq2s_grid[e];
        h_tab_split[1024 + e] = (uint32_t) (h_iq2s_grid[e] >> 32);
    }

    std::mt19937 rng(1234);
    std::vector<uint8_t> h_pool(blob * NE);
    for (auto& v : h_pool) v = (uint8_t) rng();
    for (size_t i = 0; i < h_pool.size() / sizeof(block_iq2_s); ++i) {
        const float d = 0.002f + 0.006f * (float) (rng() % 1000) / 1000.0f;
        ((block_iq2_s*) h_pool.data())[i].d = sycl::bit_cast<uint16_t>(sycl::half(d));
    }
    std::vector<block_q8_1> h_x(E / 32);
    std::vector<float> xf(E);
    for (int b = 0; b < E / 32; ++b) {
        const float d = 0.01f;
        int s = 0;
        for (int j = 0; j < 32; ++j) {
            h_x[b].qs[j] = (int8_t) ((int) (rng() % 255) - 127);
            s += h_x[b].qs[j];
            xf[b * 32 + j] = d * h_x[b].qs[j];
        }
        h_x[b].ds = sycl::half2(d, d * s);
    }
    uint8_t* d_pool = sycl::malloc_device<uint8_t>(h_pool.size(), q);
    block_q8_1* d_x = sycl::malloc_device<block_q8_1>(h_x.size(), q);
    uint32_t* d_tab64 = sycl::malloc_device<uint32_t>(2048, q);
    uint32_t* d_tab16 = sycl::malloc_device<uint32_t>(512, q);
    uint32_t* d_tabs = sycl::malloc_device<uint32_t>(2048, q);
    float *d_g = sycl::malloc_device<float>(K * FF, q), *d_u = sycl::malloc_device<float>(K * FF, q);
    uint64_t* d_plans = sycl::malloc_device<uint64_t>(K * NPLAN, q);
    q.memcpy(d_pool, h_pool.data(), h_pool.size());
    q.memcpy(d_x, h_x.data(), h_x.size() * sizeof(block_q8_1));
    q.memcpy(d_tab64, h_iq2s_grid, sizeof(h_iq2s_grid));
    q.memcpy(d_tab16, h_tab16.data(), 512 * 4);
    q.memcpy(d_tabs, h_tab_split.data(), 2048 * 4);
    std::vector<uint64_t> h_plans(K * NPLAN);
    std::vector<int> ids(NE);
    for (int p = 0; p < NPLAN; ++p) {
        for (int i = 0; i < NE; ++i) ids[i] = i;
        std::shuffle(ids.begin(), ids.end(), rng);
        for (int j = 0; j < K; ++j) h_plans[p * K + j] = (uint64_t) (d_pool + (size_t) ids[j] * blob);
    }
    q.memcpy(d_plans, h_plans.data(), h_plans.size() * 8).wait();
    auto args = [&](int p) { return GuArgs{d_plans + (size_t) (p % NPLAN) * K, d_x, d_g, d_u, nullptr, K, E, FF}; };

    struct Arm { const char* name; std::function<void(const GuArgs&)> fn; bool exact; };
    std::vector<Arm> arms = {
        {"live  t0 r2 c1", [&](const GuArgs& a) { gu2::launch<0, 2, 1>(q, a, d_tab64); }, true},
        {"u16   t1 r2 c1", [&](const GuArgs& a) { gu2::launch<1, 2, 1>(q, a, d_tab16); }, true},
        {"u16g  t2 r2 c1", [&](const GuArgs& a) { gu2::launch<2, 2, 1>(q, a, d_tab16); }, true},
        {"split t3 r2 c1", [&](const GuArgs& a) { gu2::launch<3, 2, 1>(q, a, d_tabs); }, true},
        {"live  t0 r4 c1", [&](const GuArgs& a) { gu2::launch<0, 4, 1>(q, a, d_tab64); }, true},
        {"u16   t1 r4 c1", [&](const GuArgs& a) { gu2::launch<1, 4, 1>(q, a, d_tab16); }, true},
        {"live  t0 r2 c2", [&](const GuArgs& a) { gu2::launch<0, 2, 2>(q, a, d_tab64); }, true},
        {"u16   t1 r2 c2", [&](const GuArgs& a) { gu2::launch<1, 2, 2>(q, a, d_tab16); }, true},
        {"u16   t1 r2 c4", [&](const GuArgs& a) { gu2::launch<1, 2, 4>(q, a, d_tab16); }, true},
        {"AL    t0 r2", [&](const GuArgs& a) { gu2::launch_al<0, 2>(q, a, d_tab64); }, true},
        {"AL    t1 r2", [&](const GuArgs& a) { gu2::launch_al<1, 2>(q, a, d_tab16); }, true},
        {"AL    t3 r2", [&](const GuArgs& a) { gu2::launch_al<3, 2>(q, a, d_tabs); }, true},
        {"AL    t0 r4", [&](const GuArgs& a) { gu2::launch_al<0, 4>(q, a, d_tab64); }, true},
        {"AL    t1 r4", [&](const GuArgs& a) { gu2::launch_al<1, 4>(q, a, d_tab16); }, true},
        {"ALF   t0 r2", [&](const GuArgs& a) { gu2::launch_al<0, 2, true>(q, a, d_tab64); }, true},
        {"ALF   t1 r2", [&](const GuArgs& a) { gu2::launch_al<1, 2, true>(q, a, d_tab16); }, true},
        {"ALF   t0 r4", [&](const GuArgs& a) { gu2::launch_al<0, 4, true>(q, a, d_tab64); }, true},
        {"ALF   t1 r4", [&](const GuArgs& a) { gu2::launch_al<1, 4, true>(q, a, d_tab16); }, true},
        {"IMM   t0 r2", [&](const GuArgs& a) { gu2::launch_imm<0, 2>(q, a, d_tab64); }, true},
        {"IMM   t0 r4", [&](const GuArgs& a) { gu2::launch_imm<0, 4>(q, a, d_tab64); }, true},
        {"IMM   t3 r2", [&](const GuArgs& a) { gu2::launch_imm<3, 2>(q, a, d_tabs); }, true},
        {"RPL sg16 ks1", [&](const GuArgs& a) { gu2::launch_rpl<16, 1>(q, a, d_tab64); }, false},
        {"RPL sg16 ks2", [&](const GuArgs& a) { gu2::launch_rpl<16, 2>(q, a, d_tab64); }, false},
        {"RPL sg16 ks4", [&](const GuArgs& a) { gu2::launch_rpl<16, 4>(q, a, d_tab64); }, false},
        {"RPL sg32 ks1", [&](const GuArgs& a) { gu2::launch_rpl<32, 1>(q, a, d_tab64); }, false},
        {"RPL sg32 ks2", [&](const GuArgs& a) { gu2::launch_rpl<32, 2>(q, a, d_tab64); }, false},
        {"RPL sg32 ks4", [&](const GuArgs& a) { gu2::launch_rpl<32, 4>(q, a, d_tab64); }, false},
        {"DIAG nolookup", [&](const GuArgs& a) { gu2::launch<9, 2, 1>(q, a, nullptr); }, false},
        {"DIAG peak-read", [&](const GuArgs& a) { gu2::launch_peak(q, a); }, false},
    };

    // ---- correctness: the live replica against the CPU reference, every exact arm bit-for-bit against the replica
    std::vector<float> ref_g(K * FF), ref_u(K * FF), w(E);
    for (int j = 0; j < K; ++j) {
        const size_t e = (h_plans[j] - (uint64_t) d_pool) / blob;
        for (int r = 0; r < 2 * FF; ++r) {
            ref_dequant_iq2s((const block_iq2_s*) (h_pool.data() + e * blob + (size_t) r * rb), E, w.data());
            double s = 0;
            for (int c = 0; c < E; ++c) s += (double) w[c] * xf[c];
            (r < FF ? ref_g[j * FF + r] : ref_u[j * FF + r - FF]) = (float) s;
        }
    }
    auto run0 = [&](const Arm& arm, std::vector<float>& g, std::vector<float>& u) {
        q.memset(d_g, 0, K * FF * 4);
        q.memset(d_u, 0, K * FF * 4);
        arm.fn(args(0));
        g.resize(K * FF);
        u.resize(K * FF);
        q.memcpy(g.data(), d_g, K * FF * 4);
        q.memcpy(u.data(), d_u, K * FF * 4).wait();
    };
    std::vector<float> g0, u0;
    run0(arms[0], g0, u0);
    double maxref = 0, maxerr = 0;
    for (int i = 0; i < K * FF; ++i) {
        maxref = std::max({maxref, (double) std::fabs(ref_g[i]), (double) std::fabs(ref_u[i])});
        maxerr = std::max({maxerr, (double) std::fabs(g0[i] - ref_g[i]), (double) std::fabs(u0[i] - ref_u[i])});
    }
    bool all_ok = maxerr / maxref < 2e-3;
    std::printf("live replica vs CPU reference: max |err| / max |ref| = %.2e %s\n", maxerr / maxref,
                all_ok ? "OK" : "FAIL");
    std::vector<int> bitok(arms.size(), 1);
    for (size_t a = 1; a < arms.size(); ++a) {
        if (!arms[a].exact && std::strncmp(arms[a].name, "RPL", 3) == 0) {
            std::vector<float> g, u;
            run0(arms[a], g, u);
            double md = 0, me = 0;
            size_t same = 0;
            for (int i = 0; i < K * FF; ++i) {
                md = std::max({md, (double) std::fabs(g[i] - g0[i]), (double) std::fabs(u[i] - u0[i])});
                me = std::max({me, (double) std::fabs(g[i] - ref_g[i]), (double) std::fabs(u[i] - ref_u[i])});
                same += (g[i] == g0[i]) + (u[i] == u0[i]);
            }
            const bool ok = me / maxref < 2e-3;
            all_ok = all_ok && ok;
            std::printf("%-16s vs live: max |diff| / max |ref| = %.2e (%zu of %d identical); vs CPU ref %.2e %s\n",
                        arms[a].name, md / maxref, same, 2 * K * FF, me / maxref, ok ? "OK" : "FAIL");
            continue;
        }
        if (!arms[a].exact) continue;
        std::vector<float> g, u;
        run0(arms[a], g, u);
        size_t bad = 0;
        for (int i = 0; i < K * FF; ++i)
            bad += sycl::bit_cast<uint32_t>(g[i]) != sycl::bit_cast<uint32_t>(g0[i]) ||
                   sycl::bit_cast<uint32_t>(u[i]) != sycl::bit_cast<uint32_t>(u0[i]);
        bitok[a] = bad == 0;
        all_ok = all_ok && bad == 0;
        std::printf("%-16s bit-exact vs live: %s (%zu of %d differ)\n", arms[a].name, bad ? "NO" : "yes", bad, K * FF);
    }

    // ---- speed: per-launch GPU time between barriers, plans rotated; each arm timed twice in A B .. B A order
    const double bytes = (double) K * blob + E / 32 * sizeof(block_q8_1);
    std::vector<double> t1(arms.size()), t2(arms.size());
    auto timeit = [&](const Arm& arm) {
        for (int i = 0; i < 20; ++i) arm.fn(args(i));
        q.wait();
        std::vector<double> v(iters);
        for (int i = 0; i < iters; ++i) {
            const GuArgs a = args(i);
            sycl::event e0 = q.ext_oneapi_submit_barrier();
            arm.fn(a);
            sycl::event e1 = q.ext_oneapi_submit_barrier();
            e1.wait();
            v[i] = (double) (e1.get_profiling_info<sycl::info::event_profiling::command_end>() -
                             e0.get_profiling_info<sycl::info::event_profiling::command_end>()) / 1e3;
        }
        std::sort(v.begin(), v.end());
        return v[iters / 2];   // median us
    };
    for (size_t a = 0; a < arms.size(); ++a) t1[a] = timeit(arms[a]);
    for (size_t a = arms.size(); a-- > 0;) t2[a] = timeit(arms[a]);
    std::printf("\n%-16s %9s %9s %8s %8s\n", "arm", "med1 us", "med2 us", "GB/s", "vs live");
    const double tl = 0.5 * (t1[0] + t2[0]);
    for (size_t a = 0; a < arms.size(); ++a) {
        const double t = 0.5 * (t1[a] + t2[a]);
        std::printf("%-16s %9.2f %9.2f %8.1f %7.3fx%s\n", arms[a].name, t1[a], t2[a], bytes / (t * 1e3), tl / t,
                    arms[a].exact && !bitok[a] ? "  NOT EXACT" : "");
    }
    return all_ok ? 0 : 1;
}
