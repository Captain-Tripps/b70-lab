// bench_h2d.cpp - host USM <-> device copy bandwidth and small-copy latency on each visible GPU, one shared context
// (as Strata's Windows port uses), fresh per process.  Looks for a per-start slow state.
#include <sycl/sycl.hpp>
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <vector>

static double ms_since(std::chrono::steady_clock::time_point t) {
    return std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t).count();
}

int main() {
    std::vector<sycl::device> gpus;
    for (auto& d : sycl::device::get_devices())
        if (d.is_gpu()) gpus.push_back(d);
    sycl::context ctx(gpus);
    const size_t big = 256u << 20, small = 16384;
    char* h = sycl::malloc_host<char>(big, ctx);
    for (size_t i = 0; i < big; i += 4096) h[i] = 1;
    for (size_t g = 0; g < gpus.size(); ++g) {
        sycl::queue q(ctx, gpus[g], sycl::property::queue::in_order());
        char* d = sycl::malloc_device<char>(big, q);
        q.memcpy(d, h, big).wait();
        double h2d = 1e9, d2h = 1e9, lat = 1e9;
        for (int r = 0; r < 4; ++r) {
            auto t = std::chrono::steady_clock::now(); q.memcpy(d, h, big).wait(); h2d = std::min(h2d, ms_since(t));
            t = std::chrono::steady_clock::now(); q.memcpy(h, d, big).wait(); d2h = std::min(d2h, ms_since(t));
        }
        auto t = std::chrono::steady_clock::now();
        for (int r = 0; r < 200; ++r) { q.memcpy(d, h, small); q.memcpy(h, d, small); }
        q.wait();
        lat = ms_since(t) / 400.0 * 1000.0;
        std::printf("gpu%zu h2d %.1f GB/s d2h %.1f GB/s small %.1f us\n", g, big / h2d / 1e6, big / d2h / 1e6, lat);
        sycl::free(d, q);
    }
    sycl::free(h, ctx);
    return 0;
}
