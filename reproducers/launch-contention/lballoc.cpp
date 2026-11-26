// lballoc: host cost of a kernel launch from several threads, each on its own GPU and in-order queue.
// Started as a check of whether launch cost grows with the number of live USM allocations (it does not), then used to
// show that threads launching into one shared sycl::context slow each other down, and that a context per thread does not.
// Usage: lballoc <threads> <N> <device allocs per thread> <host allocs per thread> <first GPU> <own context 0/1>
// 32 B argument kernel, parallel_for with an event, N launches per thread after a 200-launch warm-up.
#include <sycl/sycl.hpp>
#include <barrier>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <thread>
#include <vector>
using clk = std::chrono::steady_clock;

int main(int argc, char** argv) {
    const int nt = argc > 1 ? std::atoi(argv[1]) : 1;
    const int N = argc > 2 ? std::atoi(argv[2]) : 2000;
    const int K = argc > 3 ? std::atoi(argv[3]) : 0;
    const int KH = argc > 4 ? std::atoi(argv[4]) : 0;
    const int D0 = argc > 5 ? std::atoi(argv[5]) : 0;   // first GPU index (multi-process test)
    const int CX = argc > 6 ? std::atoi(argv[6]) : 0;   // 1: each thread its own sycl::context
    auto gpus = sycl::device::get_devices(sycl::info::device_type::gpu);
    const int ng = (int) gpus.size();
    std::vector<double> res((size_t) nt, 0.0);
    std::barrier bar(nt);
    std::vector<std::thread> th;
    for (int t = 0; t < nt; ++t)
        th.emplace_back([&, t] {
            try {
                sycl::device dev = gpus[(size_t) ((t + D0) % ng)];
                sycl::queue q = CX ? sycl::queue(sycl::context(dev), dev, sycl::property_list{sycl::property::queue::in_order()})
                                   : sycl::queue(dev, sycl::property_list{sycl::property::queue::in_order()});
                float* a = sycl::malloc_device<float>(4096, q);
                std::vector<void*> extra;
                for (int i = 0; i < K; ++i) extra.push_back(sycl::malloc_device(65536, q));
                for (int i = 0; i < KH; ++i) extra.push_back(sycl::malloc_host(4096, q));
                const float* b = a + 1024; const float* c = a + 2048; float* o = a + 3072;
                auto one = [&](int i) {
                    const float k = (float) i; const int n = 256;
                    q.parallel_for(sycl::nd_range<1>(256, 256), [=](sycl::nd_item<1> it) {
                        const int j = (int) it.get_global_id(0); if (j < n) o[j] = b[j] * k + c[j]; });
                };
                for (int i = 0; i < 200; ++i) one(i);
                q.wait();
                bar.arrive_and_wait();
                auto t0 = clk::now();
                for (int i = 0; i < N; ++i) one(i);
                res[(size_t) t] = std::chrono::duration<double, std::micro>(clk::now() - t0).count() / N;
                q.wait();
                for (void* p : extra) sycl::free(p, q);
                sycl::free(a, q);
            } catch (const std::exception& e) { std::fprintf(stderr, "thread %d: %s\n", t, e.what()); std::fflush(stderr); std::_Exit(3); }
        });
    for (auto& x : th) x.join();
    double s = 0; for (double v : res) s += v;
    std::printf("gpu0 %d threads %d GPUs %d N %d dev-allocs %d host-allocs %d ctx %d : %.2f us/launch\n", D0, nt, ng, N, K, KH, CX, s / nt);
    return 0;
}
