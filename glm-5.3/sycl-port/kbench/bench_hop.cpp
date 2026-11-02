// bench_hop.cpp - the floor of a card-to-card hand-off, done the way Maya does it: a kernel on card A copies the
// 16 KB activation (n_embd floats) into pinned host memory, card B is ordered after it, a kernel on B copies it in
// and does a tiny step, then the same back to A, round and round.  Per-hop wall time for three ways of ordering B
// after A:  (h) the host waits on A's event before submitting B's work (the old path), (t) B's queue gets a
// host_task that waits on A's event (fixups17, no host block), (s) no ordering at all: B's kernel spins on a flag
// in host memory that A's kernel sets after its data (system-scope atomics; each card has its own context).
// This is the number that decides whether per-layer exchanges (an expert-parallel split) can pay off.
#include <sycl/sycl.hpp>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <vector>

using sys_ref = sycl::atomic_ref<unsigned, sycl::memory_order::acq_rel, sycl::memory_scope::system,
                                 sycl::access::address_space::global_space>;

static int run_main(int argc, char** argv) {
    const int N = 4096, iters = argc > 1 ? std::atoi(argv[1]) : 2000;
    std::vector<sycl::device> gpus;
    for (auto& d : sycl::device::get_devices())
        if (d.is_gpu()) gpus.push_back(d);
    if (gpus.size() < 2) { std::printf("need 2 gpus, found %zu\n", gpus.size()); return 1; }
    sycl::queue qa(gpus[0], sycl::property::queue::in_order()), qb(gpus[1], sycl::property::queue::in_order());
    float *a = sycl::malloc_device<float>(N, qa), *b = sycl::malloc_device<float>(N, qb);
    float *hab = sycl::malloc_host<float>(N, qa), *hba = sycl::malloc_host<float>(N, qa);   // A->B, B->A slots
    unsigned* flags = sycl::malloc_host<unsigned>(2, qa);                                   // [0] A->B, [1] B->A
    qa.memset(a, 0, N * 4).wait();
    qb.memset(b, 0, N * 4).wait();
    // one step on a card: read its input slot, write its own activation, push it to the output slot
    auto step = [N](sycl::queue& q, const float* in, float* act, float* out) {
        return q.parallel_for(sycl::range<1>(N), [=](sycl::id<1> i) {
            const float v = in[i] * 0.5f + 1.0f;
            act[i] = v;
            out[i] = v;
        });
    };
    // the spin variant: one work-group waits for the flag, then the step; the producer sets its flag after the data
    auto step_spin = [N](sycl::queue& q, const float* in, float* act, float* out, unsigned* wait_f, unsigned want,
                         unsigned* set_f) {
        return q.parallel_for(sycl::nd_range<1>(sycl::range<1>(N), sycl::range<1>(N > 1024 ? 1024 : N)),
                              [=](sycl::nd_item<1> it) {
            // single work-group would limit N; use 4 groups, each spins itself (cheap: one load per lane)
            if (it.get_local_id(0) == 0) {
                sys_ref f(*wait_f);
                while (f.load() < want) {}
            }
            sycl::group_barrier(it.get_group());
            sycl::atomic_fence(sycl::memory_order::acquire, sycl::memory_scope::system);
            const size_t i = it.get_global_id(0);
            const float v = in[i] * 0.5f + 1.0f;
            act[i] = v;
            out[i] = v;
            sycl::atomic_fence(sycl::memory_order::release, sycl::memory_scope::system);
            sycl::group_barrier(it.get_group());
            if (it.get_local_id(0) == 0) {
                sys_ref f(*set_f);
                f.fetch_add(1u);   // the consumer waits for all 4 groups: want counts groups
            }
        });
    };
    auto run = [&](const char* name, int mode) {
        flags[0] = flags[1] = 0;
        const unsigned groups = (unsigned) (N / (N > 1024 ? 1024 : N));
        auto t0 = std::chrono::steady_clock::now();
        if (mode == 2) {
            // everything is enqueued up front: the cards order themselves through the flags.  A goes first
            // (it waits for B->A count 0, which holds), B waits for A's groups each round.
            for (int it = 0; it < iters; ++it) {
                step_spin(qa, hba, a, hab, &flags[1], groups * (unsigned) it, &flags[0]);
                step_spin(qb, hab, b, hba, &flags[0], groups * (unsigned) (it + 1), &flags[1]);
            }
        } else {
            for (int it = 0; it < iters; ++it) {
                sycl::event ea = step(qa, hba, a, hab);
                if (mode == 0) ea.wait();
                else qb.submit([&](sycl::handler& h) { h.host_task([ea]() mutable { ea.wait(); }); });
                sycl::event eb = step(qb, hab, b, hba);
                if (mode == 0) eb.wait();
                else qa.submit([&](sycl::handler& h) { h.host_task([eb]() mutable { eb.wait(); }); });
            }
        }
        qa.wait();
        qb.wait();
        const double us = std::chrono::duration<double, std::micro>(std::chrono::steady_clock::now() - t0).count();
        std::printf("%-26s %8.1f us per hop (step + 16 KB through host memory + ordering)\n", name, us / (2.0 * iters));
    };
    for (int rep = 0; rep < 2; ++rep) {
        run("host wait (old)", 0);
        run("host_task (fixups17)", 1);
        run("device spin on flag", 2);
    }
    // single-card reference: the same steps back to back on one queue, no other card, no ordering
    auto t0 = std::chrono::steady_clock::now();
    for (int it = 0; it < iters; ++it) { step(qa, hba, a, hab); step(qa, hab, a, hba); }
    qa.wait();
    const double us = std::chrono::duration<double, std::micro>(std::chrono::steady_clock::now() - t0).count();
    std::printf("%-26s %8.1f us per step (one card, no hop)\n", "reference", us / (2.0 * iters));
    return 0;
}

int main(int argc, char** argv) {
    std::setvbuf(stdout, nullptr, _IONBF, 0);
    try {
        return run_main(argc, argv);
    } catch (const std::exception& e) {
        std::printf("exception: %s\n", e.what());
        return 2;
    }
}
