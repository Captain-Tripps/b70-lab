// clk.cpp - does the B70 (Level Zero) support the SYCL device clock, and what rate does it tick at?
#include <sycl/sycl.hpp>
#include <sycl/ext/oneapi/experimental/clock.hpp>
#include <chrono>
#include <cstdio>
namespace sx = sycl::ext::oneapi::experimental;
int main() {
    std::setvbuf(stdout, nullptr, _IONBF, 0);
    try {
        sycl::queue q(sycl::gpu_selector_v);
        const auto d = q.get_device();
        std::printf("%s  clock aspects: sub_group %d work_group %d device %d\n", d.get_info<sycl::info::device::name>().c_str(),
                    (int) d.has(sycl::aspect::ext_oneapi_clock_sub_group), (int) d.has(sycl::aspect::ext_oneapi_clock_work_group),
                    (int) d.has(sycl::aspect::ext_oneapi_clock_device));
        unsigned long long* t = sycl::malloc_shared<unsigned long long>(2, q);
        auto w0 = std::chrono::steady_clock::now();
        q.single_task([=] {
            const unsigned long long a = sx::clock<sx::clock_scope::sub_group>();
            volatile float x = 1.0f;
            for (int i = 0; i < 20000000; ++i) x = x * 1.0000001f + 1e-9f;
            t[0] = a;
            t[1] = sx::clock<sx::clock_scope::sub_group>();
        }).wait();
        const double us = std::chrono::duration<double, std::micro>(std::chrono::steady_clock::now() - w0).count();
        std::printf("ticks %llu over ~%.0f us wall -> ~%.1f ticks/us\n", t[1] - t[0], us, (double) (t[1] - t[0]) / us);
    } catch (const std::exception& e) { std::printf("exception: %s\n", e.what()); return 2; }
    return 0;
}
