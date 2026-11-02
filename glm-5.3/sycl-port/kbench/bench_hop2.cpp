// bench_hop2.cpp - Maya's card-to-card hop in ONE shared context (as strata_device_context makes on Windows), with
// K small kernels queued behind the ordering on each card (a card's layers).  Per hop: wall time and the host time
// spent submitting.  Orderings: (h) host waits on A's event, (t) host_task on B waiting for A's event (fixups17/24),
// (b) B's queue gets ext_oneapi_submit_barrier({A's event}) - a device-side cross-device wait, (d) B's first kernel
// depends_on(A's event).  The question: does (b)/(d) work on the L0 v1 adapter, and does it keep B's kernels on the
// direct submission path (host_task puts every kernel behind it through the SYCL scheduler).
#include <sycl/sycl.hpp>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <vector>

static int run_main(int argc, char** argv) {
    const int N = 4096, iters = argc > 1 ? std::atoi(argv[1]) : 300, K = argc > 2 ? std::atoi(argv[2]) : 40, W = argc > 3 ? std::atoi(argv[3]) : 1;
    std::vector<sycl::device> gpus;
    for (auto& d : sycl::device::get_devices())
        if (d.is_gpu()) gpus.push_back(d);
    if (gpus.size() < 2) { std::printf("need 2 gpus, found %zu\n", gpus.size()); return 1; }
    sycl::context ctx(std::vector<sycl::device>{gpus[0], gpus[1]});
    sycl::queue qa(ctx, gpus[0], sycl::property::queue::in_order()), qb(ctx, gpus[1], sycl::property::queue::in_order());
    float *a = sycl::malloc_device<float>(N, qa), *b = sycl::malloc_device<float>(N, qb);
    float *hab = sycl::malloc_host<float>(N, qa), *hba = sycl::malloc_host<float>(N, qa);
    qa.memset(a, 0, N * 4).wait();
    qb.memset(b, 0, N * 4).wait();
    for (int i = 0; i < N; ++i) hab[i] = hba[i] = 0.0f;
    auto step = [N](sycl::queue& q, const float* in, float* act, float* out) {
        return q.parallel_for(sycl::range<1>(N), [=](sycl::id<1> i) { const float v = in[i] * 0.5f + 1.0f; act[i] = v; out[i] = v; });
    };
    auto layers = [N, K, W](sycl::queue& q, float* act) {
        for (int k = 0; k < K; ++k) q.parallel_for(sycl::range<1>(N), [=](sycl::id<1> i) { float v = act[i]; for (int w = 0; w < W; ++w) v = v * 0.999f + 0.001f; act[i] = v; });
    };
    auto order = [&](sycl::queue& q, sycl::event e, int mode) {
        if (mode == 0) e.wait();
        else if (mode == 1) q.submit([&](sycl::handler& h) { h.host_task([e]() mutable { e.wait(); }); });
        else if (mode == 2) q.ext_oneapi_submit_barrier({e});
    };
    auto run = [&](const char* name, int mode) {
        double sub = 0.0;
        auto t0 = std::chrono::steady_clock::now();
        for (int it = 0; it < iters; ++it) {
            auto s0 = std::chrono::steady_clock::now();
            layers(qa, a);
            sycl::event ea = step(qa, a, a, hab);
            auto s1 = std::chrono::steady_clock::now();
            sub += std::chrono::duration<double, std::micro>(s1 - s0).count();
            order(qb, ea, mode);
            s0 = std::chrono::steady_clock::now();
            sycl::event eb;
            if (mode == 3) eb = qb.submit([&](sycl::handler& h) { h.depends_on(ea); h.parallel_for(sycl::range<1>(N), [=](sycl::id<1> i) { b[i] = hab[i]; }); });
            else eb = qb.parallel_for(sycl::range<1>(N), [=](sycl::id<1> i) { b[i] = hab[i]; });
            layers(qb, b);
            eb = step(qb, b, b, hba);
            s1 = std::chrono::steady_clock::now();
            sub += std::chrono::duration<double, std::micro>(s1 - s0).count();
            order(qa, eb, mode);
            s0 = std::chrono::steady_clock::now();
            if (mode == 3) qa.submit([&](sycl::handler& h) { h.depends_on(eb); h.parallel_for(sycl::range<1>(N), [=](sycl::id<1> i) { a[i] = hba[i]; }); });
            else qa.parallel_for(sycl::range<1>(N), [=](sycl::id<1> i) { a[i] = hba[i]; });
            sub += std::chrono::duration<double, std::micro>(std::chrono::steady_clock::now() - s0).count();
        }
        qa.wait();
        qb.wait();
        const double us = std::chrono::duration<double, std::micro>(std::chrono::steady_clock::now() - t0).count();
        float chk = 0.0f;
        qa.memcpy(&chk, a, 4).wait();
        std::printf("%-30s %8.1f us per hop, host submit %6.2f us per kernel  (check %.4f)\n", name, us / (2.0 * iters),
                    sub / (iters * (2.0 * K + 4.0)), chk);
    };
    std::printf("K = %d kernels per card per hop\n", K);
    for (int rep = 0; rep < 2; ++rep) {
        run("host wait", 0);
        run("host_task (current)", 1);
        run("submit_barrier cross-device", 2);
        run("depends_on cross-device", 3);
    }
    return 0;
}

int main(int argc, char** argv) {
    std::setvbuf(stdout, nullptr, _IONBF, 0);
    try { return run_main(argc, argv); } catch (const std::exception& e) { std::printf("exception: %s\n", e.what()); return 2; }
}
