// idle: host cost of a launch onto an in-order queue that just went idle (after q.wait()), vs the next launches.
// 4 cards, a context each (as DS4_QCTX=1). Per card: R reps of { wait; launch k0; launch k1..k7 } on one thread, then
// the same with all 4 cards in turn from one thread (as rollback does). Usage: idle [reps] [idle_us]
#include <sycl/sycl.hpp>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <thread>
#include <vector>
using clk = std::chrono::steady_clock;
static double us(clk::time_point a, clk::time_point b) { return std::chrono::duration<double, std::micro>(b - a).count(); }
int main(int argc, char** argv) {
    const int R = argc > 1 ? std::atoi(argv[1]) : 200;
    const int idle_us = argc > 2 ? std::atoi(argv[2]) : 0;
    const int spin = argc > 3 ? std::atoi(argv[3]) : 0;   // 1: idle by busy-spinning, not sleeping
    auto idle = [&]() {
        if (idle_us <= 0) return;
        if (!spin) { std::this_thread::sleep_for(std::chrono::microseconds(idle_us)); return; }
        const auto t = clk::now();
        while (us(t, clk::now()) < idle_us) {}
    };
    auto gpus = sycl::device::get_devices(sycl::info::device_type::gpu);
    std::vector<sycl::context> ctx;
    std::vector<sycl::queue> q;
    std::vector<float*> b;
    for (size_t c = 0; c < gpus.size() && c < 4; ++c) {
        ctx.emplace_back(gpus[c]);
        q.emplace_back(ctx.back(), gpus[c], sycl::property::queue::in_order());
        b.push_back(sycl::malloc_device<float>(4096, q.back()));
    }
    auto k = [&](size_t c) {
        float* p = b[c];
        q[c].parallel_for(sycl::nd_range<1>(256, 256), [=](sycl::nd_item<1> it) { p[it.get_global_id(0)] += 1.0f; });
    };
    for (size_t c = 0; c < q.size(); ++c) { for (int i = 0; i < 50; ++i) k(c); q[c].wait(); }
    for (size_t c = 0; c < q.size(); ++c) {
        double first = 0, rest = 0;
        for (int r = 0; r < R; ++r) {
            q[c].wait();
            idle();
            const auto t0 = clk::now();
            k(c);
            const auto t1 = clk::now();
            for (int i = 0; i < 7; ++i) k(c);
            const auto t2 = clk::now();
            first += us(t0, t1);
            rest += us(t1, t2) / 7;
        }
        q[c].wait();
        std::printf("card %zu: first launch after wait %.1f us, next launches %.1f us each (idle %d us)\n", c, first / R,
                    rest / R, idle_us);
    }
    {   // the 4 cards in turn after waiting on all of them (rollback's shape)
        double tot = 0;
        for (int r = 0; r < R; ++r) {
            for (auto& qq : q) qq.wait();
            idle();
            const auto t0 = clk::now();
            for (size_t c = 0; c < q.size(); ++c) { k(c); k(c); }
            tot += us(t0, clk::now());
        }
        for (auto& qq : q) qq.wait();
        std::printf("4 cards x 2 launches after idle: %.1f us in all (%.1f a launch)\n", tot / R, tot / R / (2 * q.size()));
    }
    return 0;
}
