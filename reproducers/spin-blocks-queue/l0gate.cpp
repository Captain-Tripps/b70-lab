// l0gate: does a Level Zero host-signalled event, waited on by queue Q2's command list, stall OTHER queues on the same
// GPU? (A spinning gate kernel does: it blocks every queue on a B70.) Usage: l0gate <mode 0 = one context, 1 = a
// context per queue> [N gated kernels = 800] [M other kernels = 200]
#include <level_zero/ze_api.h>   // (the real API first: this oneAPI's interop header only declares the handle types)
#include <sycl/sycl.hpp>
#include <sycl/ext/oneapi/backend/level_zero.hpp>
#include <windows.h>
#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <thread>
#include <variant>
using clk = std::chrono::steady_clock;
static double ms(clk::time_point a, clk::time_point b) { return std::chrono::duration<double, std::milli>(b - a).count(); }

// the few Level Zero calls, from the loader the driver installed (no import library needed)
static decltype(&zeEventPoolCreate) pPoolCreate;
static decltype(&zeEventCreate) pEventCreate;
static decltype(&zeEventHostSignal) pHostSignal;
static decltype(&zeEventHostReset) pHostReset;
static decltype(&zeCommandListAppendWaitOnEvents) pAppendWait;
static decltype(&zeEventDestroy) pEventDestroy;
static decltype(&zeEventPoolDestroy) pPoolDestroy;
template <class F> static void sym(HMODULE h, F& f, const char* n) {
    f = (F) GetProcAddress(h, n);
    if (!f) { std::printf("missing %s\n", n); std::exit(3); }
}

struct KTag;
static void tiny(sycl::queue& q, float* b) {
    q.parallel_for<KTag>(sycl::nd_range<1>(256, 256), [=](sycl::nd_item<1> it) { b[it.get_global_id(0)] += 1.0f; });
}

int main(int argc, char** argv) {
    const int mode = argc > 1 ? std::atoi(argv[1]) : 0;
    const int N = argc > 2 ? std::atoi(argv[2]) : 800;
    const int M = argc > 3 ? std::atoi(argv[3]) : 200;
    HMODULE h = LoadLibraryA("ze_loader.dll");
    if (!h) { std::printf("no ze_loader.dll\n"); return 3; }
    sym(h, pPoolCreate, "zeEventPoolCreate");
    sym(h, pEventCreate, "zeEventCreate");
    sym(h, pHostSignal, "zeEventHostSignal");
    sym(h, pHostReset, "zeEventHostReset");
    sym(h, pAppendWait, "zeCommandListAppendWaitOnEvents");
    sym(h, pEventDestroy, "zeEventDestroy");
    sym(h, pPoolDestroy, "zeEventPoolDestroy");

    auto gpus = sycl::device::get_devices(sycl::info::device_type::gpu);
    sycl::device dev = gpus[0];
    sycl::context c1(dev);
    sycl::context c2 = mode ? sycl::context(dev) : c1;
    sycl::queue q1(c1, dev, sycl::property::queue::in_order());
    sycl::queue q2(c2, dev, sycl::property::queue::in_order());
    float* b1 = sycl::malloc_device<float>(256, q1);
    float* b2 = sycl::malloc_device<float>(256, q2);
    q1.memset(b1, 0, 1024).wait();
    q2.memset(b2, 0, 1024).wait();
    for (int i = 0; i < 8; ++i) { tiny(q1, b1); tiny(q2, b2); }
    q1.wait(); q2.wait();

    auto nq = sycl::get_native<sycl::backend::ext_oneapi_level_zero>(q2);
    ze_command_list_handle_t* cl = std::get_if<ze_command_list_handle_t>(&nq);
    if (!cl) { std::printf("Q2 is not an immediate command list (got a command queue) - stop\n"); return 4; }
    ze_context_handle_t zc = sycl::get_native<sycl::backend::ext_oneapi_level_zero>(c2);
    ze_device_handle_t zd = sycl::get_native<sycl::backend::ext_oneapi_level_zero>(dev);

    ze_event_pool_desc_t pd = {ZE_STRUCTURE_TYPE_EVENT_POOL_DESC, nullptr, ZE_EVENT_POOL_FLAG_HOST_VISIBLE, 1};
    ze_event_pool_handle_t pool = nullptr;
    if (pPoolCreate(zc, &pd, 1, &zd, &pool) != ZE_RESULT_SUCCESS) { std::printf("pool create failed\n"); return 5; }
    ze_event_desc_t ed = {ZE_STRUCTURE_TYPE_EVENT_DESC, nullptr, 0, ZE_EVENT_SCOPE_FLAG_HOST, ZE_EVENT_SCOPE_FLAG_HOST};
    ze_event_handle_t ev = nullptr;
    if (pEventCreate(pool, &ed, &ev) != ZE_RESULT_SUCCESS) { std::printf("event create failed\n"); return 5; }

    std::atomic<bool> done{false};
    std::thread dog([&] {   // (watchdog: a gate that blocks everything would hang here)
        const auto t0 = clk::now();
        while (!done.load()) {
            if (ms(t0, clk::now()) > 8000) { std::printf("HANG (watchdog 8 s)\n"); std::fflush(stdout); pHostSignal(ev); std::exit(2); }
            std::this_thread::sleep_for(std::chrono::milliseconds(20));
        }
    });

    std::printf("mode %s, N %d gated, M %d other\n", mode ? "a context per queue" : "one context", N, M);
    for (int rep = 0; rep < 3; ++rep) {
        // baseline: Q2's N fresh, Q1's M alongside
        auto a = clk::now();
        for (int i = 0; i < N; ++i) tiny(q2, b2);
        auto b = clk::now();
        for (int i = 0; i < M; ++i) tiny(q1, b1);
        q1.wait();
        auto c = clk::now();
        q2.wait();
        auto d = clk::now();
        std::printf("  rep %d fresh: Q2 enqueue %.2f ms | Q1 %d kernels + wait %.2f ms | Q2 done %.2f ms after its enqueue\n",
                    rep, ms(a, b), M, ms(b, c), ms(b, d));
        // gated: Q2 waits on the host event, N behind it; Q1 runs M meanwhile; then the host opens the gate
        pHostReset(ev);
        if (pAppendWait(*cl, 1, &ev) != ZE_RESULT_SUCCESS) { std::printf("append wait failed\n"); return 6; }
        std::printf("    gate appended\n"); std::fflush(stdout);
        a = clk::now();
        for (int i = 0; i < N; ++i) tiny(q2, b2);
        b = clk::now();
        std::printf("    Q2 %d enqueued in %.2f ms\n", N, ms(a, b)); std::fflush(stdout);
        for (int i = 0; i < M; ++i) tiny(q1, b1);
        std::printf("    Q1 %d enqueued in %.2f ms\n", M, ms(b, clk::now())); std::fflush(stdout);
        q1.wait();
        c = clk::now();
        std::printf("    Q1 done\n"); std::fflush(stdout);
        std::this_thread::sleep_for(std::chrono::milliseconds(2));   // (the gate held a bit longer, Q2 must not run)
        auto s0 = clk::now();
        pHostSignal(ev);
        q2.wait();
        d = clk::now();
        std::printf("  rep %d gated: Q2 enqueue %.2f ms | Q1 %d kernels + wait %.2f ms (while gated) | Q2 done %.2f ms after signal\n",
                    rep, ms(a, b), M, ms(b, c), ms(s0, d));
    }
    done = true;
    dog.join();
    float h1[256], h2[256];
    q1.memcpy(h1, b1, 1024).wait();
    q2.memcpy(h2, b2, 1024).wait();
    const float e1 = 8 + 3.0f * 2 * M, e2 = 8 + 3.0f * 2 * N;
    std::printf("check: Q1 %s (%.0f vs %.0f), Q2 %s (%.0f vs %.0f)\n", h1[0] == e1 && h1[255] == e1 ? "OK" : "BAD", h1[0], e1,
                h2[0] == e2 && h2[255] == e2 ? "OK" : "BAD", h2[0], e2);
    pEventDestroy(ev);
    pPoolDestroy(pool);
    sycl::free(b1, q1);
    sycl::free(b2, q2);
    return 0;
}
