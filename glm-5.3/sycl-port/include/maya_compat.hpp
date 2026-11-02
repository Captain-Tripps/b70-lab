// maya_compat.hpp - CUDA runtime names dpct left unmigrated in the Maya GLM port, mapped to SYCL/dpct.
// Included by tools/maya_fixups.py after <dpct/dpct.hpp> in the files that use them.
#pragma once
#include <cstdio>
#include <thread>
#include <cstdlib>
#include <sycl/sycl.hpp>
#include <dpct/dpct.hpp>
#include <cstring>

using cudaStream_t = dpct::queue_ptr;
using cudaEvent_t = dpct::event_ptr;

#ifndef cudaEventDisableTiming
#define cudaEventDisableTiming 0u
#endif

// cudaGraphDestroy: dpct 2025.3 emits `delete (graph)`; the daily build left the call.
template <class G> inline int cudaGraphDestroy(G* g) { delete g; return 0; }

// cudaLaunchHostFunc on an in-order queue: a host_task keeps the stream order.
inline int cudaLaunchHostFunc(dpct::queue_ptr q, void (*fn)(void*), void* p) {
    (q ? q : &dpct::get_in_order_queue())->submit([&](sycl::handler& h) { h.host_task([=] { fn(p); }); });
    return 0;
}

// Device attributes / PCI ids have no portable SYCL query: report failure so callers take their fallback.
enum { cudaDevAttrMemoryClockRate = 36, cudaDevAttrGlobalMemoryBusWidth = 37, cudaDevAttrMaxSharedMemoryPerBlock = 8 };
inline int cudaDeviceGetAttribute(int* v, int, int) { if (v) *v = 0; return 1; }
inline int cudaDeviceGetPCIBusId(char* bus, int n, int) { if (bus && n > 0) bus[0] = 0; return 1; }

// Device-side round-to-nearest add / cycle counter (profiling only: no SPIR-V clock, reads zero).
inline float __fadd_rn(float a, float b) { return a + b; }
inline long long clock64() { return 0; }

// SYCL port (fixups12): a copy as a kernel - on B70/Windows/L0 a USM host<->device copy queued behind a running
// kernel blocks every other host copy in the context until that kernel ends (spin4.cpp)
inline sycl::event maya_kcopy(sycl::queue* q, void* dst, const void* src, size_t bytes) {
    if (bytes % 4 == 0) {
        unsigned* d = (unsigned*) dst; const unsigned* s = (const unsigned*) src;
        return q->parallel_for(sycl::range<1>(bytes / 4), [=](sycl::id<1> i) { d[i] = s[i]; });
    }
    unsigned char* d = (unsigned char*) dst; const unsigned char* s = (const unsigned char*) src;
    return q->parallel_for(sycl::range<1>(bytes), [=](sycl::id<1> i) { d[i] = s[i]; });
}

// SYCL port (fixups17): queue q's later work behind another device's event without blocking the calling thread - a
// host task on q waits for it (a cross-device barrier aborts in UR on Windows L0).  MAYA_HOP_HOSTWAIT=1: block here.
inline void maya_queue_wait(sycl::queue* q, sycl::event* ev, bool spec = false) {
    // SYCL port (fixups24): overlapped on the L0 v1 adapter (the v2 adapter deadlocks in the driver when the SYCL
    // worker thread and this thread launch kernels at once); MAYA_HOP_SYNC=1 blocks, MAYA_HOP_ASYNC=1 forces overlap
    static const bool block = [] {
        const char* v2 = std::getenv("SYCL_UR_USE_LEVEL_ZERO_V2");
        const bool v1 = v2 != nullptr && v2[0] == '0';
        const bool b = std::getenv("MAYA_HOP_SYNC") != nullptr || (!v1 && std::getenv("MAYA_HOP_ASYNC") == nullptr);
        std::fprintf(stderr, "glm hop: %s (L0 adapter %s)\n", b ? "blocking" : "overlapped", v1 ? "v1" : "v2");
        return b;
    }();
    // SYCL port (fixups22): the MTP head->tail hop on its own switch (MAYA_HOP_SPEC_ASYNC=0/1; default as above)
    static const int spec_sw = std::getenv("MAYA_HOP_SPEC_ASYNC") ? std::atoi(std::getenv("MAYA_HOP_SPEC_ASYNC")) : -1;
    if (spec ? (spec_sw < 0 ? block : spec_sw == 0) : block) { ev->wait(); return; }
    // SYCL port (fixups25): a device-side wait - a host task blocks every later submit to q until it ends
    static const bool host_task = std::getenv("MAYA_HOP_HOSTTASK") != nullptr;
    if (!host_task) { q->ext_oneapi_submit_barrier({*ev}); return; }
    sycl::event e = *ev;
    // SYCL port (fixups20): poll the status - a blocking wait here deadlocked L0 against the submitting thread
    static const bool block_task = std::getenv("MAYA_HOP_BLOCKWAIT") != nullptr;
    if (block_task) { q->submit([&](sycl::handler& h) { h.host_task([e]() mutable { e.wait(); }); }); return; }
    q->submit([&](sycl::handler& h) {
        h.host_task([e]() {
            while (e.get_info<sycl::info::event::command_execution_status>() !=
                   sycl::info::event_command_status::complete) std::this_thread::yield();
        });
    });
}

// SYCL port (fixups18): the sub-group cycle counter for the route kernel's profile (clock64 above stays a stub)
#include <sycl/ext/oneapi/experimental/clock.hpp>
inline long long maya_dev_clock() {
#ifdef __SYCL_DEVICE_ONLY__
    return (long long) sycl::ext::oneapi::experimental::clock<sycl::ext::oneapi::experimental::clock_scope::sub_group>();
#else
    return 0;
#endif
}

// SYCL port (fixups32): Windows' getenv takes the CRT's environment lock, and the decode path calls it per launch and
// per poll (the four expert-service threads checked MAYA_TRACE on every spin) - the enqueue threads queued on that
// lock (~70% of host samples).  maya_env caches each name per thread (no lock); maya_env_changed(), called after every
// putenv/setenv, makes the next lookups re-read.  Values are never freed, so a returned pointer stays valid.
#include <atomic>
#include <deque>
#include <string>
#include <unordered_map>
inline std::atomic<unsigned> maya_env_gen{0};
inline void maya_env_changed() { maya_env_gen.fetch_add(1, std::memory_order_release); }
inline const char* maya_env(const char* name) {
    struct E { unsigned gen; const char* v; };
    thread_local std::unordered_map<std::string, E> cache;
    thread_local std::deque<std::string> vals;
    thread_local std::string key;
    const unsigned g = maya_env_gen.load(std::memory_order_acquire);
    key.assign(name);
    auto it = cache.find(key);
    if (it != cache.end() && it->second.gen == g) return it->second.v;
    const char* v = std::getenv(name);
    const char* keep = nullptr;
    if (v != nullptr) {
        if (it != cache.end() && it->second.v != nullptr && std::strcmp(it->second.v, v) == 0) keep = it->second.v;
        else { vals.emplace_back(v); keep = vals.back().c_str(); }
    }
    cache[key] = E{g, keep};
    return keep;
}
