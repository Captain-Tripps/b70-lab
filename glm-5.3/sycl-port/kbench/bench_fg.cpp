// bench_fg.cpp - the prompt path's grouped MoE GEMM (maya_fg_grouped: the fork's XMX dequant GEMM) alone on one card,
// at GLM-5.3-Flash Maya-M's shapes: 288 experts, 8 a token, n_embd 4096, n_ff 2048; gate/up IQ2_S (M 4096, K 4096),
// down IQ3_S / IQ3_XXS (M 4096, K 2048); 1024 tokens -> 8192 rows spread over the experts like a router would.
// Random weight bytes with sane block scales (timing only). argv: tokens(1024) reps(5) down_type(21)
#include <sycl/sycl.hpp>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <random>
#include <vector>
#include <cstdarg>
extern "C" void ggml_log_internal(int, const char* fmt, ...) { va_list a; va_start(a, fmt); std::vfprintf(stderr, fmt, a); va_end(a); }
extern "C" const char* ggml_type_name(int t) { static char b[16]; std::snprintf(b, sizeof b, "type%d", t); return b; }
extern "C" void ggml_abort(const char* f, int l, const char* fmt, ...) { std::fprintf(stderr, "abort %s:%d", f, l); std::abort(); }
extern "C" int maya_fg_type_ok(int type);
extern "C" int maya_fg_grouped(void* queue, int type, const void* w, size_t stride, const float* x, float* dst,
                               const int64_t* offs, int64_t n_as, int64_t M, int64_t K);
static size_t row_bytes(int type, int64_t K) {   // IQ2_S 82 B / 256, IQ3_S 110 B / 256, IQ3_XXS 98 B / 256
    const int b = type == 22 ? 82 : type == 21 ? 110 : type == 18 ? 98 : 0;
    return (size_t) (K / 256) * b;
}
int main(int argc, char** argv) {
    std::setvbuf(stdout, nullptr, _IONBF, 0);
    const int T = argc > 1 ? std::atoi(argv[1]) : 1024, reps = argc > 2 ? std::atoi(argv[2]) : 5, dt = argc > 3 ? std::atoi(argv[3]) : 21;
    const int NE = 288, KE = 8, E = 4096, NFF = 2048;
    try {
        sycl::queue q(sycl::gpu_selector_v, sycl::property::queue::in_order());
        std::printf("%s | types ok: gu %d down %d\n", q.get_device().get_info<sycl::info::device::name>().c_str(), maya_fg_type_ok(22), maya_fg_type_ok(dt));
        const size_t gu_b = 2 * NFF * row_bytes(22, E), dn_b = (size_t) E * row_bytes(dt, NFF), stride = gu_b + dn_b;
        std::vector<uint8_t> h(stride * NE);
        std::mt19937 rng(1);
        for (auto& b : h) b = (uint8_t) rng();
        // every 256-weight block starts with an fp16 scale: 0x2000 (~0.0078) keeps the sums finite
        const auto fix = [&](size_t off, size_t bytes, int bb) { for (size_t o = off; o + bb <= off + bytes; o += bb) { h[o] = 0x00; h[o + 1] = 0x20; } };
        for (int e = 0; e < NE; ++e) { fix((size_t) e * stride, gu_b, 82); fix((size_t) e * stride + gu_b, dn_b, dt == 21 ? 110 : 98); }
        uint8_t* w = sycl::malloc_device<uint8_t>(h.size(), q);
        q.memcpy(w, h.data(), h.size()).wait();
        // rows per expert: T tokens pick 8 distinct experts each, skewed a little (some experts hot)
        std::vector<int> cnt(NE, 0);
        for (int t = 0; t < T; ++t) { std::vector<int> s; while ((int) s.size() < KE) { int e = rng() % NE; bool dup = false; for (int x : s) dup |= x == e; if (!dup) s.push_back(e); } for (int e : s) ++cnt[e]; }
        std::vector<int64_t> offs(NE + 1, 0);
        for (int e = 0; e < NE; ++e) offs[e + 1] = offs[e] + cnt[e];
        const int64_t R = offs[NE];
        int mx = 0; for (int c : cnt) mx = std::max(mx, c);
        std::printf("rows %lld, avg %.1f max %d an expert\n", (long long) R, (double) R / NE, mx);
        float* x = sycl::malloc_device<float>((size_t) R * E, q);
        float* gu = sycl::malloc_device<float>((size_t) R * 2 * NFF, q);
        float* hx = sycl::malloc_device<float>((size_t) R * NFF, q);
        float* out = sycl::malloc_device<float>((size_t) R * E, q);
        q.parallel_for(sycl::range<1>((size_t) R * E), [=](sycl::id<1> i) { x[i] = (float) ((i[0] * 2654435761u) % 1000) * 0.001f - 0.5f; });
        q.parallel_for(sycl::range<1>((size_t) R * NFF), [=](sycl::id<1> i) { hx[i] = (float) ((i[0] * 40503u) % 1000) * 0.001f - 0.5f; }).wait();
        for (int r = 0; r < reps; ++r) {
            auto t0 = std::chrono::steady_clock::now();
            if (!maya_fg_grouped(&q, 22, w, stride, x, gu, offs.data(), NE, 2 * NFF, E)) { std::printf("gu declined\n"); return 3; }
            q.wait();
            auto t1 = std::chrono::steady_clock::now();
            if (!maya_fg_grouped(&q, dt, w + gu_b, stride, hx, out, offs.data(), NE, E, NFF)) { std::printf("down declined\n"); return 3; }
            q.wait();
            auto t2 = std::chrono::steady_clock::now();
            const double a = std::chrono::duration<double, std::milli>(t1 - t0).count(), b = std::chrono::duration<double, std::milli>(t2 - t1).count();
            const double fl_gu = 2.0 * R * 2 * NFF * E, fl_dn = 2.0 * R * E * NFF;
            std::printf("rep %d: gate/up %.2f ms (%.1f TFLOPS, %.0f GB/s w)  down %.2f ms (%.1f TFLOPS, %.0f GB/s w)  total %.2f ms\n", r, a, fl_gu / a / 1e9,
                        NE * gu_b / a / 1e6, b, fl_dn / b / 1e9, NE * dn_b / b / 1e6, a + b);
        }
        float chk[4];
        q.memcpy(chk, out, sizeof chk).wait();
        std::printf("out[0..3] %g %g %g %g\n", chk[0], chk[1], chk[2], chk[3]);
    } catch (const std::exception& e) { std::printf("exception: %s\n", e.what()); return 2; }
    return 0;
}
