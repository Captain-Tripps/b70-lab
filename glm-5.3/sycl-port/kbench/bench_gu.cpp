// bench_gu.cpp - correctness + speed of an IQ2_S MoE gate/up kernel variant against the baseline.
// Build: icpx -fsycl -O3 -std=c++17 -DVARIANT=\"variant_gu.hpp\" bench_gu.cpp -o bench_gu.exe
// The variant header must define  namespace var { void launch_gu(sycl::queue&, const GuArgs&); }
// Shapes are the real model's: k = 8 of the experts, n_embd = 4096, n_ff = 2048 (gate rows then up rows per expert).
#include "common.hpp"
#include "baseline_gu.hpp"
#ifndef VARIANT
#define VARIANT "variant_gu.hpp"
#endif
#include VARIANT

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <random>
#include <vector>

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
    const int iters = argc > 1 ? std::atoi(argv[1]) : 300;
    const size_t rb = (size_t) (E / QK_K) * sizeof(block_iq2_s), blob = 2 * (size_t) FF * rb;
    sycl::queue q(sycl::gpu_selector_v, {sycl::property::queue::in_order(), sycl::property::queue::enable_profiling()});
    std::printf("device: %s\n", q.get_device().get_info<sycl::info::device::name>().c_str());

    std::mt19937 rng(1234);
    std::vector<uint8_t> h_pool(blob * NE);
    for (auto& v : h_pool) v = (uint8_t) rng();
    for (size_t i = 0; i < h_pool.size() / sizeof(block_iq2_s); ++i) {   // sane fp16 scales
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
    uint64_t* d_grid = sycl::malloc_device<uint64_t>(1024, q);
    float *d_g = sycl::malloc_device<float>(K * FF, q), *d_u = sycl::malloc_device<float>(K * FF, q);
    uint64_t* d_plans = sycl::malloc_device<uint64_t>(K * NPLAN, q);
    q.memcpy(d_pool, h_pool.data(), h_pool.size());
    q.memcpy(d_x, h_x.data(), h_x.size() * sizeof(block_q8_1));
    q.memcpy(d_grid, h_iq2s_grid, sizeof(h_iq2s_grid));
    std::vector<uint64_t> h_plans(K * NPLAN);
    std::vector<int> ids(NE);
    for (int p = 0; p < NPLAN; ++p) {
        for (int i = 0; i < NE; ++i) ids[i] = i;
        std::shuffle(ids.begin(), ids.end(), rng);
        for (int j = 0; j < K; ++j) h_plans[p * K + j] = (uint64_t) (d_pool + (size_t) ids[j] * blob);
    }
    q.memcpy(d_plans, h_plans.data(), h_plans.size() * 8).wait();
    // a variant that defines VAR_REPACK reads its own copy of the pool, rewritten row by row by var::repack_row
    // (same bytes per row, a different layout - what a loader would do once when the experts are uploaded)
    uint64_t* d_plans_v = d_plans;
#ifdef VAR_REPACK
    std::vector<uint8_t> h_pool2(h_pool.size());
    for (size_t r = 0; r < h_pool.size() / rb; ++r) var::repack_row(h_pool.data() + r * rb, h_pool2.data() + r * rb, E);
    uint8_t* d_pool2 = sycl::malloc_device<uint8_t>(h_pool2.size(), q);
    q.memcpy(d_pool2, h_pool2.data(), h_pool2.size());
    std::vector<uint64_t> h_plans2(h_plans.size());
    for (size_t i = 0; i < h_plans.size(); ++i) h_plans2[i] = h_plans[i] - (uint64_t) d_pool + (uint64_t) d_pool2;
    d_plans_v = sycl::malloc_device<uint64_t>(h_plans2.size(), q);
    q.memcpy(d_plans_v, h_plans2.data(), h_plans2.size() * 8).wait();
#endif

    auto args = [&](int p) { return GuArgs{d_plans + (size_t) (p % NPLAN) * K, d_x, d_g, d_u, d_grid, K, E, FF}; };
    auto args_v = [&](int p) { return GuArgs{d_plans_v + (size_t) (p % NPLAN) * K, d_x, d_g, d_u, d_grid, K, E, FF}; };

    // ---- correctness: plan 0 against the CPU reference (dequantized weights x dequantized activations)
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
    auto check = [&](const char* name, auto launch, auto argf) {
        q.memset(d_g, 0, K * FF * 4);
        q.memset(d_u, 0, K * FF * 4);
        launch(q, argf(0));
        std::vector<float> g(K * FF), u(K * FF);
        q.memcpy(g.data(), d_g, K * FF * 4);
        q.memcpy(u.data(), d_u, K * FF * 4).wait();
        double maxref = 0, maxerr = 0;
        for (int i = 0; i < K * FF; ++i) {
            maxref = std::max({maxref, (double) std::fabs(ref_g[i]), (double) std::fabs(ref_u[i])});
            maxerr = std::max({maxerr, (double) std::fabs(g[i] - ref_g[i]), (double) std::fabs(u[i] - ref_u[i])});
        }
        const double rel = maxerr / maxref;
        std::printf("%-9s correctness: max |err| / max |ref| = %.2e  %s\n", name, rel, rel < 2e-3 ? "OK" : "FAIL");
        return rel < 2e-3;
    };
    const bool ok_b = check("baseline", base::launch_gu, args);
    const bool ok_v = check("variant", var::launch_gu, args_v);

    // ---- speed: GPU time per launch from profiling events, plans rotated so the experts come from memory
    auto timeit = [&](const char* name, auto launch, auto argf) {
        for (int i = 0; i < 20; ++i) launch(q, argf(i));
        q.wait();
        // per-launch GPU time: the gap between the barriers around each launch
        double ns = 0;
        for (int i = 0; i < iters; ++i) {
            const GuArgs a = argf(i);
            sycl::event e0 = q.ext_oneapi_submit_barrier();
            launch(q, a);
            sycl::event e1 = q.ext_oneapi_submit_barrier();
            e1.wait();
            ns += (double) (e1.get_profiling_info<sycl::info::event_profiling::command_end>() -
                            e0.get_profiling_info<sycl::info::event_profiling::command_end>());
        }
        const double us = ns / iters / 1e3;
        const double bytes = (double) K * blob + E / 32 * sizeof(block_q8_1);
        std::printf("%-9s %8.2f us/launch  %7.1f GB/s (weights read once)\n", name, us, bytes / (us * 1e3));
        return us;
    };
    const double tb = timeit("baseline", base::launch_gu, args);
    const double tv = timeit("variant", var::launch_gu, args_v);
    std::printf("speedup %.3fx  %s\n", tb / tv, ok_b && ok_v ? "" : "(VARIANT FAILED CORRECTNESS)");
    return ok_b && ok_v ? 0 : 1;
}
