// q2spin: does a kernel spinning on a host-USM flag in one in-order queue block another queue's kernels on the same
// GPU?  Usage: q2spin <device index> <mode>  mode 0: plain second queue, 1: low priority spin queue, 2: high priority
// work queue, 3: spin on the work queue's own context but a separate sycl::context (should not matter).
#include <sycl/sycl.hpp>
#include <sycl/ext/intel/esimd.hpp>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <thread>

int main(int argc, char** argv) {
    const int di = argc > 1 ? std::atoi(argv[1]) : 0;
    const int mode = argc > 2 ? std::atoi(argv[2]) : 0;
    auto gpus = sycl::device::get_devices(sycl::info::device_type::gpu);
    if (di >= (int) gpus.size()) { std::printf("no device %d (%zu)\n", di, gpus.size()); return 1; }
    sycl::device dev = gpus[(size_t) di];
    sycl::context ctx(dev);
    sycl::property_list pw = mode == 2 ? sycl::property_list{sycl::property::queue::in_order(), sycl::ext::oneapi::property::queue::priority_high()}
                                       : sycl::property_list{sycl::property::queue::in_order()};
    sycl::property_list ps = mode == 1 ? sycl::property_list{sycl::property::queue::in_order(), sycl::ext::oneapi::property::queue::priority_low()}
                                       : sycl::property_list{sycl::property::queue::in_order()};
    sycl::queue work(ctx, dev, pw), spin(ctx, dev, ps);
    std::printf("device %d: %s, mode %d\n", di, dev.get_info<sycl::info::device::name>().c_str(), mode);
    unsigned* flag = sycl::malloc_host<unsigned>(1, ctx);
    float* buf = sycl::malloc_device<float>(1 << 20, dev, ctx);
    *(volatile unsigned*) flag = 0;
    const unsigned* f = flag;
    sycl::event se = spin.single_task([=]() SYCL_ESIMD_KERNEL {
        namespace es = sycl::ext::intel::esimd;
        es::simd<uint32_t, 1> off(0u);
        for (unsigned i = 0; i < 0x40000000u; ++i) {
            es::fence<es::memory_kind::global, es::fence_flush_op::invalidate, es::fence_scope::system>();
            es::simd<unsigned, 1> r = es::gather<unsigned, 1>(f, off);
            if ((int) ((unsigned) r[0] - 1u) >= 0) break;
        }
    });
    spin.ext_oneapi_prod();
    std::this_thread::sleep_for(std::chrono::milliseconds(200));
    auto t0 = std::chrono::steady_clock::now();
    sycl::event we = work.parallel_for(sycl::range<1>(1 << 20), [=](sycl::id<1> i) { buf[i] = (float) i[0] * 0.5f; });
    work.ext_oneapi_prod();
    bool done = false;
    double ms = 0;
    for (;;) {
        ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
        if (we.get_info<sycl::info::event::command_execution_status>() == sycl::info::event_command_status::complete) { done = true; break; }
        if (ms > 5000) break;
        std::this_thread::sleep_for(std::chrono::microseconds(100));
    }
    const auto ss = se.get_info<sycl::info::event::command_execution_status>();
    std::printf("work kernel while the other queue spins: %s after %.1f ms (spin %s)\n", done ? "DONE" : "BLOCKED", ms,
                ss == sycl::info::event_command_status::complete ? "ended" : "still running");
    *(volatile unsigned*) flag = 1;
    auto t1 = std::chrono::steady_clock::now();
    se.wait();
    we.wait();
    std::printf("after the flag: both done in %.1f ms\n", std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t1).count());
    sycl::free(flag, ctx);
    sycl::free(buf, ctx);
    return done ? 0 : 2;
}
