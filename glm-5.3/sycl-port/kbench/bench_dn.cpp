// bench_dn.cpp - the IQ3_S MoE expert DOWN product: out[r] = sum_e w_e * dot(down_e row r, h_e), k = 8 experts,
// n_embd = 4096 output rows, n_ff = 2048 inputs (IQ3_S rows of 880 bytes, 3.6 MB an expert).  The production
// layout: a work-group of 8 sub-groups of 32 (sub-group w = expert w) computes NR output rows for all 8 experts,
// codebook copied to local memory per work-group, partials combined in plan order.  Configs differ in NR (rows a
// work-group) only; correctness against a CPU reference, time per launch from profiling events.
#include "common.hpp"
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <random>
#include <vector>

struct DnArgs {
    const uint64_t* plan;     // k blob addresses
    const float* w;           // k routing weights
    const block_q8_1* h;      // k * n_ff / 32 q8_1 blocks (each expert's swiglu output)
    float* out;               // n_embd
    const uint32_t* grid;     // iq3s_grid (512 x u32)
    int k, n_embd, n_ff;
};

inline float dw_iq3s(const uint8_t* row, int kbx, int iqs, const int* xu, float xd, const uint32_t* tab) {
    const block_iq3_s* bq3 = (const block_iq3_s*) row + kbx;
    const sycl::int2 qs_packed(get_int_b2(bq3->qs, iqs + 0), get_int_b2(bq3->qs, iqs + 1));
    const uint8_t* qs = (const uint8_t*) &qs_packed;
    const int qh = bq3->qh[iqs / 2];
    const int signs_packed_32 = get_int_b2(bq3->signs, iqs / 2);
    const uint8_t* s8 = (const uint8_t*) &signs_packed_32;
    int sumi = 0;
#pragma unroll
    for (int l0 = 0; l0 < 8; l0 += 2) {
        const uint32_t gx = tab[qs[l0 + 0] | ((qh << (8 - l0)) & 0x100)];
        const uint32_t gy = tab[qs[l0 + 1] | ((qh << (7 - l0)) & 0x100)];
        const uint32_t sb = s8[l0 / 2];
        const uint32_t m0 = (((sb & 0x0Fu) * 0x00204081u) & 0x01010101u) * 0xFFu;
        const uint32_t m1 = ((((sb >> 4) & 0x0Fu) * 0x00204081u) & 0x01010101u) * 0xFFu;
        sumi = dp4a((int) ((gx ^ m0) + (m0 & 0x01010101u)), xu[l0 + 0], sumi);
        sumi = dp4a((int) ((gy ^ m1) + (m1 & 0x01010101u)), xu[l0 + 1], sumi);
    }
    sumi *= 1 + 2 * ((bq3->scales[iqs / 4] >> ((iqs << 1) & 0x04)) & 0x0F);
    return h2f(bq3->d) * xd * sumi;
}

template <int NR>
void launch_dn(sycl::queue& q, const DnArgs& a) {
    const size_t drb = (size_t) (a.n_ff / QK_K) * sizeof(block_iq3_s);
    q.submit([&](sycl::handler& hd) {
        sycl::local_accessor<uint32_t, 1> s_tab(sycl::range<1>(512), hd);
        sycl::local_accessor<float, 2> s_part(sycl::range<2>(8, NR), hd);
        const DnArgs A = a;
        hd.parallel_for(sycl::nd_range<1>(sycl::range<1>((size_t) (A.n_embd / NR) * 256), sycl::range<1>(256)),
                        [=](sycl::nd_item<1> it) [[sycl::reqd_sub_group_size(32)]] {
            const int tid = (int) it.get_local_id(0), lane = tid & 31, warp = tid >> 5;
            for (int i = tid; i < 512; i += 256) s_tab[i] = A.grid[i];
            sycl::group_barrier(it.get_group());
            const int r0 = (int) it.get_group(0) * NR;
            float s[NR];
#pragma unroll
            for (int j = 0; j < NR; ++j) s[j] = 0.0f;
            if (warp < A.k) {
                const uint8_t* base = (const uint8_t*) A.plan[warp];
                const block_q8_1* hx = A.h + (size_t) warp * (A.n_ff / 32);
                const int nb = A.n_ff / QK_K;
                for (int kk = lane; kk < nb * 8; kk += 32) {
                    const int kbx = kk / 8, ki = kk % 8;
                    const block_q8_1* xb = hx + kbx * 8 + ki;
                    int xu[8];
#pragma unroll
                    for (int i = 0; i < 8; ++i) xu[i] = ((const int*) xb->qs)[i];
                    const float xd = (float) xb->ds.x();
#pragma unroll
                    for (int j = 0; j < NR; ++j)
                        s[j] += dw_iq3s(base + (size_t) (r0 + j) * drb, kbx, 2 * ki, xu, xd, &s_tab[0]);
                }
                const auto sg = it.get_sub_group();
#pragma unroll
                for (int j = 0; j < NR; ++j) s[j] = sycl::reduce_over_group(sg, s[j], sycl::plus<float>());
            }
            if (lane == 0)
#pragma unroll
                for (int j = 0; j < NR; ++j) s_part[warp][j] = s[j];
            sycl::group_barrier(it.get_group());
            if (tid < NR) {
                float m = 0.0f;
                for (int i = 0; i < A.k; ++i) m += A.w[i] * s_part[i][tid];
                A.out[r0 + tid] = m;
            }
        });
    });
}

static void ref_dequant_iq3s(const block_iq3_s* b, int n, float* y) {
    static const uint8_t kmask[8] = {1, 2, 4, 8, 16, 32, 64, 128};
    for (int i = 0; i < n / QK_K; ++i) {
        const float d = h2f(b[i].d);
        const uint8_t *qs = b[i].qs, *qh = b[i].qh, *signs = b[i].signs;
        for (int ib32 = 0; ib32 < QK_K / 32; ib32 += 2) {
            const float db1 = d * (1 + 2 * (b[i].scales[ib32 / 2] & 0xf));
            const float db2 = d * (1 + 2 * (b[i].scales[ib32 / 2] >> 4));
            for (int half = 0; half < 2; ++half) {
                const float db = half ? db2 : db1;
                for (int l = 0; l < 4; ++l) {
                    const uint8_t* g1 = (const uint8_t*) (h_iq3s_grid + (qs[2 * l + 0] | ((qh[half] << (8 - 2 * l)) & 256)));
                    const uint8_t* g2 = (const uint8_t*) (h_iq3s_grid + (qs[2 * l + 1] | ((qh[half] << (7 - 2 * l)) & 256)));
                    for (int j = 0; j < 4; ++j) {
                        y[j] = db * g1[j] * (signs[l] & kmask[j] ? -1.f : 1.f);
                        y[j + 4] = db * g2[j] * (signs[l] & kmask[j + 4] ? -1.f : 1.f);
                    }
                    y += 8;
                }
                qs += 8;
                signs += 4;
            }
            qh += 2;
        }
    }
}

int main(int argc, char** argv) {
    const int K = 8, E = 4096, FF = 2048, NE = 48, NPLAN = 64;
    const int iters = argc > 1 ? std::atoi(argv[1]) : 300;
    const size_t drb = (size_t) (FF / QK_K) * sizeof(block_iq3_s), blob = (size_t) E * drb;
    sycl::queue q(sycl::gpu_selector_v, {sycl::property::queue::in_order(), sycl::property::queue::enable_profiling()});
    std::printf("device: %s\n", q.get_device().get_info<sycl::info::device::name>().c_str());
    std::mt19937 rng(99);
    std::vector<uint8_t> h_pool(blob * NE);
    for (auto& v : h_pool) v = (uint8_t) rng();
    for (size_t i = 0; i < h_pool.size() / sizeof(block_iq3_s); ++i)
        ((block_iq3_s*) h_pool.data())[i].d =
            sycl::bit_cast<uint16_t>(sycl::half(0.0005f + 0.001f * (float) (rng() % 1000) / 1000.0f));
    std::vector<block_q8_1> h_h(K * FF / 32);
    std::vector<float> hf(K * FF);
    for (size_t b = 0; b < h_h.size(); ++b) {
        int s = 0;
        for (int j = 0; j < 32; ++j) {
            h_h[b].qs[j] = (int8_t) ((int) (rng() % 255) - 127);
            s += h_h[b].qs[j];
            hf[b * 32 + j] = 0.01f * h_h[b].qs[j];
        }
        h_h[b].ds = sycl::half2(0.01f, 0.01f * s);
    }
    std::vector<float> h_w(K);
    for (auto& v : h_w) v = 0.05f + 0.2f * (float) (rng() % 1000) / 1000.0f;
    uint8_t* d_pool = sycl::malloc_device<uint8_t>(h_pool.size(), q);
    block_q8_1* d_h = sycl::malloc_device<block_q8_1>(h_h.size(), q);
    float* d_w = sycl::malloc_device<float>(K, q);
    float* d_out = sycl::malloc_device<float>(E, q);
    uint32_t* d_grid = sycl::malloc_device<uint32_t>(512, q);
    uint64_t* d_plans = sycl::malloc_device<uint64_t>(K * NPLAN, q);
    q.memcpy(d_pool, h_pool.data(), h_pool.size());
    q.memcpy(d_h, h_h.data(), h_h.size() * sizeof(block_q8_1));
    q.memcpy(d_w, h_w.data(), K * 4);
    q.memcpy(d_grid, h_iq3s_grid, sizeof(h_iq3s_grid));
    std::vector<uint64_t> h_plans(K * NPLAN);
    std::vector<int> ids(NE);
    for (int p = 0; p < NPLAN; ++p) {
        for (int i = 0; i < NE; ++i) ids[i] = i;
        std::shuffle(ids.begin(), ids.end(), rng);
        for (int j = 0; j < K; ++j) h_plans[p * K + j] = (uint64_t) (d_pool + (size_t) ids[j] * blob);
    }
    q.memcpy(d_plans, h_plans.data(), h_plans.size() * 8).wait();
    auto args = [&](int p) { return DnArgs{d_plans + (size_t) (p % NPLAN) * K, d_w, d_h, d_out, d_grid, K, E, FF}; };

    std::vector<float> ref(E, 0.0f), wrow(FF);
    for (int j = 0; j < K; ++j) {
        const size_t e = (h_plans[j] - (uint64_t) d_pool) / blob;
        for (int r = 0; r < E; ++r) {
            ref_dequant_iq3s((const block_iq3_s*) (h_pool.data() + e * blob + (size_t) r * drb), FF, wrow.data());
            double s = 0;
            for (int c = 0; c < FF; ++c) s += (double) wrow[c] * hf[(size_t) j * FF + c];
            ref[r] += h_w[j] * (float) s;
        }
    }
    double t_base = 0;
    auto test = [&](const char* name, auto launch) {
        q.memset(d_out, 0, E * 4);
        launch(q, args(0));
        std::vector<float> o(E);
        q.memcpy(o.data(), d_out, E * 4).wait();
        double mr = 0, me = 0;
        for (int i = 0; i < E; ++i) { mr = std::max(mr, (double) std::fabs(ref[i])); me = std::max(me, (double) std::fabs(o[i] - ref[i])); }
        for (int i = 0; i < 20; ++i) launch(q, args(i));
        q.wait();
        double ns = 0;
        for (int i = 0; i < iters; ++i) {
            const DnArgs a = args(i);
            sycl::event e0 = q.ext_oneapi_submit_barrier();
            launch(q, a);
            sycl::event e1 = q.ext_oneapi_submit_barrier();
            e1.wait();
            ns += (double) (e1.get_profiling_info<sycl::info::event_profiling::command_end>() -
                            e0.get_profiling_info<sycl::info::event_profiling::command_end>());
        }
        const double us = ns / iters / 1e3;
        if (t_base == 0) t_base = us;
        std::printf("%-10s err %.1e %s  %8.2f us  %6.1f GB/s  %.2fx\n", name, me / mr, me / mr < 2e-3 ? "OK  " : "FAIL",
                    us, (double) K * blob / (us * 1e3), t_base / us);
    };
    test("NR=4 base", launch_dn<4>);
    test("NR=2", launch_dn<2>);
    test("NR=8", launch_dn<8>);
    test("NR=16", launch_dn<16>);
    return 0;
}
