// bench_gap.cpp - GPU-side cost of a dependent kernel on an in-order queue: N tiny kernels back to back (each reads
// and writes one small buffer, like the decode's small ops), GPU time between barriers / N.  Run with Maya's L0 env.
#include <sycl/sycl.hpp>
#include <cstdio>
#include <cstdlib>
int main(int argc, char** argv) {
    const int N = argc > 1 ? std::atoi(argv[1]) : 200;
    sycl::queue q(sycl::gpu_selector_v, {sycl::property::queue::in_order(), sycl::property::queue::enable_profiling()});
    float* b = sycl::malloc_device<float>(1 << 20, q);
    q.memset(b, 0, 4 << 20).wait();
    auto run = [&](int wg, int groups, const char* name) {
        for (int rep = 0; rep < 3; ++rep) {
            sycl::event e0 = q.ext_oneapi_submit_barrier();
            for (int i = 0; i < N; ++i)
                q.parallel_for(sycl::nd_range<1>(sycl::range<1>((size_t) wg * groups), sycl::range<1>(wg)), [=](sycl::nd_item<1> it) {
                    const size_t g = it.get_global_id(0);
                    b[g & 1048575] = b[g & 1048575] * 0.5f + 1.0f;
                });
            sycl::event e1 = q.ext_oneapi_submit_barrier();
            e1.wait();
            const double ns = (double) (e1.get_profiling_info<sycl::info::event_profiling::command_end>() -
                                        e0.get_profiling_info<sycl::info::event_profiling::command_end>());
            if (rep == 2) std::printf("%-22s %6.2f us per kernel (N=%d)\n", name, ns / N / 1e3, N);
        }
    };
    run(32, 1, "1 group of 32");
    run(256, 16, "16 groups of 256");
    run(256, 256, "256 groups of 256");
    run(256, 4096, "4096 groups of 256");
    return 0;
}
