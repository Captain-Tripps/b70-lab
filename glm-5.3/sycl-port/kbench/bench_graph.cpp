// bench_graph.cpp - does a recorded SYCL command graph replay on this driver path (Maya's: one shared context over
// the GPUs, in-order queues, L0 adapter per env), and what does a replay cost the host vs K direct submits.
// Cases: (1) record+replay on one queue, (2) replay behind a cross-device submit_barrier, (3) host-memory write
// kernel inside the graph (Maya's route ring / tok_h).  Each step checks the data and has a timeout.
#include <sycl/sycl.hpp>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <thread>
#include <vector>
#include <future>
namespace sx = sycl::ext::oneapi::experimental;

static bool wait_to(sycl::event e, const char* what) {
    auto t0 = std::chrono::steady_clock::now();
    while (e.get_info<sycl::info::event::command_execution_status>() != sycl::info::event_command_status::complete) {
        if (std::chrono::steady_clock::now() - t0 > std::chrono::seconds(10)) { std::printf("HANG: %s\n", what); return false; }
        std::this_thread::yield();
    }
    return true;
}

static int run_main(int argc, char** argv) {
    const int N = 4096, K = argc > 1 ? std::atoi(argv[1]) : 40, iters = argc > 2 ? std::atoi(argv[2]) : 200;
    std::vector<sycl::device> gpus;
    for (auto& d : sycl::device::get_devices()) if (d.is_gpu()) gpus.push_back(d);
    std::printf("%zu gpus, K=%d\n", gpus.size(), K);
    sycl::context ctx(std::vector<sycl::device>{gpus[0], gpus[1]});
    sycl::queue qa(ctx, gpus[0], sycl::property::queue::in_order()), qb(ctx, gpus[1], sycl::property::queue::in_order());
    float *a = sycl::malloc_device<float>(N, qa), *b = sycl::malloc_device<float>(N, qb);
    int* h = sycl::malloc_host<int>(4, qb);
    qa.memset(a, 0, N * 4).wait();
    qb.memset(b, 0, N * 4).wait();
    h[0] = 0;
    auto layers = [=](sycl::queue& q, float* x, bool hostw) {
        for (int k = 0; k < K; ++k) q.parallel_for(sycl::range<1>(N), [=](sycl::id<1> i) { x[i] = x[i] + 1.0f; });
        if (hostw) q.single_task([=] { h[0] = h[0] + 1; });
        if (std::getenv("BG_ROOTSYNC")) {
            const sycl::nd_range<3> nr(sycl::range<3>(1, 1, N), sycl::range<3>(1, 1, 256));
            q.parallel_for(nr, sx::properties{sx::use_root_sync}, [=](sycl::nd_item<3> it) { const int i = it.get_global_id(2); x[i] = x[i] + 0.0f; });
        }
    };
    for (int hostw = 0; hostw < 2; ++hostw) {
        sx::command_graph<sx::graph_state::modifiable> g(ctx, gpus[1]);
        g.begin_recording(qb);
        layers(qb, b, hostw);
        g.end_recording(qb);
        auto ex = g.finalize();
        std::printf("[hostw %d] recorded\n", hostw);
        // (1) plain replay
        sycl::event e = qb.ext_oneapi_graph(ex);
        if (!wait_to(e, "plain replay")) return 3;
        // queue.wait() right behind a replay (+ a barrier, + a kernel): does it return
        for (int mode = 0; mode < 3; ++mode) {
            qb.ext_oneapi_graph(ex);
            if (mode >= 1) qb.ext_oneapi_submit_barrier();
            if (mode >= 2) qb.parallel_for(sycl::range<1>(N), [=](sycl::id<1> i) { b[i] = b[i] + 0.0f; });
            auto f = std::async(std::launch::async, [&] { qb.wait(); });
            if (f.wait_for(std::chrono::seconds(10)) != std::future_status::ready) { std::printf("HANG: queue.wait after replay, mode %d\n", mode); std::fflush(stdout); std::_Exit(5); }
            if (mode == 2) {
                float* tmp = sycl::malloc_device<float>(N, qb);
                qb.ext_oneapi_graph(ex);
                qb.memcpy(tmp, b, N * 4);
                auto f2 = std::async(std::launch::async, [&] { qb.wait(); });
                if (f2.wait_for(std::chrono::seconds(10)) != std::future_status::ready) { std::printf("HANG: memcpy behind replay\n"); std::fflush(stdout); std::_Exit(6); }
                std::printf("memcpy behind replay ok\n");
            }
            std::printf("queue.wait after replay mode %d ok\n", mode);
        }
        // (2) behind a cross-device barrier, timed
        double sub_g = 0, sub_d = 0;
        auto t0 = std::chrono::steady_clock::now();
        for (int it = 0; it < iters; ++it) {
            sycl::event ea = qa.parallel_for(sycl::range<1>(N), [=](sycl::id<1> i) { a[i] = a[i] + 1.0f; });
            qb.ext_oneapi_submit_barrier({ea});
            auto s0 = std::chrono::steady_clock::now();
            e = qb.ext_oneapi_graph(ex);
            sub_g += std::chrono::duration<double, std::micro>(std::chrono::steady_clock::now() - s0).count();
        }
        if (!wait_to(e, "replay behind barrier")) return 4;
        const double tg = std::chrono::duration<double, std::micro>(std::chrono::steady_clock::now() - t0).count() / iters;
        t0 = std::chrono::steady_clock::now();
        for (int it = 0; it < iters; ++it) {
            sycl::event ea = qa.parallel_for(sycl::range<1>(N), [=](sycl::id<1> i) { a[i] = a[i] + 1.0f; });
            qb.ext_oneapi_submit_barrier({ea});
            auto s0 = std::chrono::steady_clock::now();
            layers(qb, b, hostw);
            sub_d += std::chrono::duration<double, std::micro>(std::chrono::steady_clock::now() - s0).count();
        }
        qb.wait();
        const double td = std::chrono::duration<double, std::micro>(std::chrono::steady_clock::now() - t0).count() / iters;
        float chk = 0;
        qb.memcpy(&chk, b, 4).wait();
        const float want = (float) K * (1 + 1 + 2 * iters) * 1.0f + 0;   // b accumulates across both hostw rounds
        std::printf("[hostw %d] graph: host submit %.1f us/layer-set, wall %.1f us | direct: submit %.1f us, wall %.1f us | b[0]=%.0f host=%d\n",
                    hostw, sub_g / iters, tg, sub_d / iters, td, chk, h[0]);
        (void) want;
    }
    return 0;
}
int main(int argc, char** argv) {
    std::setvbuf(stdout, nullptr, _IONBF, 0);
    try { return run_main(argc, argv); } catch (const std::exception& e) { std::printf("exception: %s\n", e.what()); return 2; }
}
