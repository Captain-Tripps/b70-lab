// bench_submit.cpp - host cost of submitting one small kernel to an in-order Level Zero queue, the ways Maya's
// converted code does it: q.parallel_for (shortcut), q.submit + handler, with the use_root_sync launch property
// (SYCLomatic puts it on ~96 kernels), with group_local_memory_for_overwrite (dpct's shared memory), and the same
// through a property list + nd_range<3>.  Host-side us per submit, the GPU kept busy behind a long first kernel so
// the numbers are pure submission cost.
#include <sycl/sycl.hpp>
#include <chrono>
#include <cstdio>
#include <cstdlib>

namespace sx = sycl::ext::oneapi::experimental;

int main(int argc, char** argv) {
    std::setvbuf(stdout, nullptr, _IONBF, 0);
    const int n = argc > 1 ? std::atoi(argv[1]) : 3000;
    try {
        const bool prof = argc > 2 && argv[2][0] == '1';
        sycl::queue q = prof ? sycl::queue(sycl::gpu_selector_v, sycl::property_list{sycl::property::queue::in_order(), sycl::property::queue::enable_profiling()})
                             : sycl::queue(sycl::gpu_selector_v, sycl::property::queue::in_order());
        std::printf("profiling %d\n", (int)prof);
        std::printf("%s\n", q.get_device().get_info<sycl::info::device::name>().c_str());
        float* a = sycl::malloc_device<float>(1 << 16, q);
        float* b = sycl::malloc_device<float>(1 << 16, q);
        const int* flag = sycl::malloc_device<int>(1, q);
        auto run = [&](const char* name, auto submit_one) {
            for (int i = 0; i < 200; ++i) submit_one();
            q.wait();
            auto t0 = std::chrono::steady_clock::now();
            for (int i = 0; i < n; ++i) submit_one();
            auto t1 = std::chrono::steady_clock::now();
            q.wait();
            auto t2 = std::chrono::steady_clock::now();
            std::printf("%-44s submit %6.2f us   (drain %6.2f us each)\n", name,
                        std::chrono::duration<double, std::micro>(t1 - t0).count() / n,
                        std::chrono::duration<double, std::micro>(t2 - t0).count() / n);
        };
        const sycl::nd_range<3> nr(sycl::range<3>(1, 1, 2048), sycl::range<3>(1, 1, 256));
        run("parallel_for shortcut (range)", [&] {
            q.parallel_for(sycl::range<1>(2048), [=](sycl::id<1> i) { b[i] = a[i] * 2.0f + (flag ? 1.0f : 0.0f); });
        });
        run("submit + handler nd_range<3>", [&] {
            q.submit([&](sycl::handler& h) {
                h.parallel_for(nr, [=](sycl::nd_item<3> it) { const int i = it.get_global_id(2); b[i] = a[i] * 2.0f; });
            });
        });
        run("shortcut nd_range<3> + use_root_sync", [&] {
            q.parallel_for(nr, sx::properties{sx::use_root_sync}, [=](sycl::nd_item<3> it) {
                const int i = it.get_global_id(2); b[i] = a[i] * 2.0f; });
        });
        run("submit + handler + use_root_sync", [&] {
            q.submit([&](sycl::handler& h) {
                h.parallel_for(nr, sx::properties{sx::use_root_sync}, [=](sycl::nd_item<3> it) {
                    const int i = it.get_global_id(2); b[i] = a[i] * 2.0f; });
            });
        });
        run("shortcut nd_range<3> + group_local_memory", [&] {
            q.parallel_for(nr, [=](sycl::nd_item<3> it) {
                auto& s = *sycl::ext::oneapi::group_local_memory_for_overwrite<float[256]>(it.get_group());
                const int l = it.get_local_id(2), i = it.get_global_id(2);
                s[l] = a[i];
                sycl::group_barrier(it.get_group());
                b[i] = s[255 - l];
            });
        });
        run("submit + local_accessor", [&] {
            q.submit([&](sycl::handler& h) {
                sycl::local_accessor<float, 1> s(sycl::range<1>(256), h);
                h.parallel_for(nr, [=](sycl::nd_item<3> it) {
                    const int l = it.get_local_id(2), i = it.get_global_id(2);
                    s[l] = a[i];
                    sycl::group_barrier(it.get_group());
                    b[i] = s[255 - l];
                });
            });
        });
        run("submit + handler, 12 captured pointers", [&] {
            float *p0 = a, *p1 = b, *p2 = a + 1, *p3 = b + 1, *p4 = a + 2, *p5 = b + 2, *p6 = a + 3, *p7 = b + 3,
                  *p8 = a + 4, *p9 = b + 4, *p10 = a + 5, *p11 = b + 5;
            q.submit([&](sycl::handler& h) {
                h.parallel_for(nr, [=](sycl::nd_item<3> it) {
                    const int i = it.get_global_id(2);
                    p1[i] = p0[i] + p2[i] + p3[i] + p4[i] + p5[i] + p6[i] + p7[i] + p8[i] + p9[i] + p10[i] + p11[i];
                });
            });
        });
        run("ext_oneapi_submit_barrier", [&] { q.ext_oneapi_submit_barrier(); });
    } catch (const std::exception& e) { std::printf("exception: %s\n", e.what()); return 2; }
    return 0;
}
