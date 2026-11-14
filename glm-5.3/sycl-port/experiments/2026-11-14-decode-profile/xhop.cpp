// Cross-card exchange cost on Level Zero without peer access: the host-staged hop the GLM engine uses
// (device A -> pinned host -> device B), and the 4-card gather/scatter an expert-parallel layer would need.
// Each measurement: median of N iterations after warm-up, wall time on the host.
#include <sycl/sycl.hpp>
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <vector>
#include <string>

using clk = std::chrono::steady_clock;
static double med(std::vector<double> v) { std::sort(v.begin(), v.end()); return v[v.size() / 2]; }

int main(int argc, char** argv) {
    auto devs = sycl::device::get_devices(sycl::info::device_type::gpu);
    const int D = (int) devs.size();
    std::printf("gpus %d\n", D);
    if (D < 2) return 1;
    std::vector<sycl::queue> q;
    for (auto& d : devs) q.emplace_back(d, sycl::property::queue::in_order{});
    if (argc > 1 && std::string(argv[1]) == "map") {
        // keep card k busy ~10 s, then idle 4 s, k = 0..D-1, so the Windows GPU Engine counters name each card
        for (int k = 0; k < D; ++k) {
            std::printf("MAP card %d start %lld\n", k, (long long) std::chrono::duration_cast<std::chrono::milliseconds>(
                std::chrono::system_clock::now().time_since_epoch()).count());
            std::fflush(stdout);
            auto t0 = clk::now();
            const size_t n = (size_t) 1 << 30;   // 4 GB of floats, touched, so Dedicated Usage shows it
            float* x = sycl::malloc_device<float>(n, q[k]);
            q[k].memset(x, 1, n * sizeof(float)).wait();
            while (clk::now() - t0 < std::chrono::seconds(10)) {}
            sycl::free(x, q[k]);
            auto t1 = clk::now();
            while (clk::now() - t1 < std::chrono::seconds(4)) {}
        }
        return 0;
    }
    const size_t sizes[] = {4096, 16384, 65536, 262144};
    const size_t maxb = 262144;
    std::vector<float*> dbuf(D), dbuf2(D);
    for (int i = 0; i < D; ++i) {
        dbuf[i] = sycl::malloc_device<float>(maxb / 4 * D, q[i]);
        dbuf2[i] = sycl::malloc_device<float>(maxb / 4 * D, q[i]);
        q[i].memset(dbuf[i], 0, maxb * D).wait();
    }
    float* host = sycl::malloc_host<float>(maxb / 4 * D, q[0]);
    const int N = 400;

    // 0. the floor: an empty kernel + host wait on one card
    {
        std::vector<double> t;
        for (int it = 0; it < N + 50; ++it) {
            auto a = clk::now();
            q[0].single_task([] {}).wait();
            if (it >= 50) t.push_back(std::chrono::duration<double, std::micro>(clk::now() - a).count());
        }
        std::printf("empty kernel + wait (card 0): %.1f us\n", med(t));
    }
    for (size_t b : sizes) {
        // 1. one hop A -> host -> B, host waits between (what the decode hop does)
        std::vector<double> t1;
        for (int it = 0; it < N + 50; ++it) {
            auto a = clk::now();
            q[0].memcpy(host, dbuf[0], b).wait();
            q[1].memcpy(dbuf[1], host, b).wait();
            if (it >= 50) t1.push_back(std::chrono::duration<double, std::micro>(clk::now() - a).count());
        }
        // 2. expert-parallel layer exchange on all D cards: scatter the token's activation from card 0 to the others,
        //    each computes (empty kernel here), gather their partial outputs back to card 0
        std::vector<double> t2;
        for (int it = 0; it < N + 50; ++it) {
            auto a = clk::now();
            q[0].memcpy(host, dbuf[0], b).wait();
            std::vector<sycl::event> e;
            for (int i = 1; i < D; ++i) e.push_back(q[i].memcpy(dbuf[i], host, b));
            for (int i = 1; i < D; ++i) q[i].single_task([] {});
            for (int i = 1; i < D; ++i) e.push_back(q[i].memcpy(host + (size_t) i * b / 4, dbuf2[i], b));
            for (int i = 1; i < D; ++i) q[i].wait();
            q[0].memcpy(dbuf2[0], host + b / 4, b * (D - 1)).wait();
            if (it >= 50) t2.push_back(std::chrono::duration<double, std::micro>(clk::now() - a).count());
        }
        std::printf("bytes %7zu | one hop A->host->B %.1f us | %d-card scatter+gather %.1f us\n", b, med(t1), D, med(t2));
    }
    // 3. per-pair one-hop at 64 KB (all pairs), to see whether any pair is slower (x4 vs x8 / switch hops)
    for (int i = 0; i < D; ++i)
        for (int j = 0; j < D; ++j) {
            if (i == j) continue;
            std::vector<double> t;
            for (int it = 0; it < 250; ++it) {
                auto a = clk::now();
                q[i].memcpy(host, dbuf[i], 65536).wait();
                q[j].memcpy(dbuf[j], host, 65536).wait();
                if (it >= 50) t.push_back(std::chrono::duration<double, std::micro>(clk::now() - a).count());
            }
            std::printf("pair %d->%d 64KB %.1f us\n", i, j, med(t));
        }
    return 0;
}
