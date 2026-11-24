// flag_test4.cpp - does a plain SYCL fence (no ESIMD) let a RUNNING kernel on card 1 see a host-USM flag written by
// the host or card 0? flag_test3: only the ESIMD system invalidate fence did. Also: are the DATA words written before
// the flag fresh after the wait (the all-reduce reads the other card's rows right after its flag)?
#include <sycl/sycl.hpp>
#include <sycl/ext/intel/esimd.hpp>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <thread>
using namespace sycl;
namespace es = sycl::ext::intel::esimd;
static const unsigned kCap = 2000000, kData = 256;
static const size_t kLine = 4096 / sizeof(unsigned), kSlots = 64;

static double ms_since(std::chrono::steady_clock::time_point t) {
    return std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t).count();
}
// res[0] loads, res[1] flag seen, res[2] data words that were stale after the wait
template <int LD> static void launch_reader(queue& q, unsigned* flag, unsigned* data, unsigned* res) {
    if constexpr (LD == 3) {
        q.single_task([=]() SYCL_ESIMD_KERNEL {
            unsigned i = 0, v = 0;
            es::simd<uint32_t, 1> off(0u);
            for (; i < kCap; ++i) {
                es::fence<es::memory_kind::global, es::fence_flush_op::invalidate, es::fence_scope::system>();
                es::simd<unsigned, 1> r = es::gather<unsigned, 1>(flag, off);
                v = r[0];
                if (v != 0u) break;
            }
            unsigned bad = 0;
            for (unsigned k = 0; k < kData; k += 16) {
                es::simd<unsigned, 16> d = es::block_load<unsigned, 16>(data + k);
                for (int j = 0; j < 16; ++j) bad += d[j] != 7u + k + j ? 1u : 0u;
            }
            es::simd<unsigned, 4> o(0u);
            o[0] = i; o[1] = v; o[2] = bad;
            es::block_store<unsigned, 4>(res, o);
        });
    } else {
        q.single_task([=] {
            unsigned i = 0, v = 0;
            for (; i < kCap; ++i) {
                if constexpr (LD == 1) atomic_fence(memory_order::acquire, memory_scope::system);
                if constexpr (LD == 2) atomic_fence(memory_order::seq_cst, memory_scope::system);
                v = *(volatile unsigned*) flag;
                if (v != 0u) break;
            }
            if constexpr (LD != 0) atomic_fence(memory_order::acquire, memory_scope::system);
            unsigned bad = 0;
            for (unsigned k = 0; k < kData; ++k) bad += ((volatile unsigned*) data)[k] != 7u + k ? 1u : 0u;
            res[0] = i; res[1] = v; res[2] = bad;
        });
    }
}
int main() {
    auto devs = device::get_devices(info::device_type::gpu);
    if (devs.size() < 2) { std::printf("need 2 GPUs\n"); return 1; }
    context ctx{{devs[0], devs[1]}};
    queue q0{ctx, devs[0], property::queue::in_order{}}, q1{ctx, devs[1], property::queue::in_order{}};
    unsigned* res = malloc_host<unsigned>(kLine, ctx);
    const char* SN[] = {"host write", "dev0 write"};
    const char* LN[] = {"volatile", "SYCL acquire+vol", "SYCL seq_cst+vol", "ESIMD inval (ctl)"};
    unsigned* base = malloc_host<unsigned>(kLine * kSlots * 2, ctx);
    std::memset(base, 0, kLine * kSlots * 2 * sizeof(unsigned));
    int slot = 0;
    for (int st = 0; st < 2; ++st)
        for (int ld = 0; ld < 4; ++ld) {
            unsigned* flag = base + kLine * (size_t) slot;
            unsigned* data = base + kLine * (size_t) (kSlots + slot);
            ++slot;
            try {
                std::memset(res, 0, 16);
                // the reader touches the data first (stale lines in its caches), then waits for the flag
                q1.single_task([=] { unsigned s = 0; for (unsigned k = 0; k < kData; ++k) s += ((volatile unsigned*) data)[k]; res[3] = s; });
                q1.wait();
                switch (ld) {
                    case 0: launch_reader<0>(q1, flag, data, res); break;
                    case 1: launch_reader<1>(q1, flag, data, res); break;
                    case 2: launch_reader<2>(q1, flag, data, res); break;
                    default: launch_reader<3>(q1, flag, data, res); break;
                }
                std::this_thread::sleep_for(std::chrono::milliseconds(50));
                auto tw = std::chrono::steady_clock::now();
                if (st == 0) {
                    for (unsigned k = 0; k < kData; ++k) ((volatile unsigned*) data)[k] = 7u + k;
                    std::atomic_thread_fence(std::memory_order_seq_cst);
                    *(volatile unsigned*) flag = 1u;
                } else {
                    q0.single_task([=] {
                        for (unsigned k = 0; k < kData; ++k) ((volatile unsigned*) data)[k] = 7u + k;
                        atomic_fence(memory_order::acq_rel, memory_scope::system);
                        *(volatile unsigned*) flag = 1u;
                    });
                    q0.wait();
                }
                q1.wait();
                std::printf("%-11s load %-18s: %-8s after %7u loads, %3u of %u data words stale; reader done %7.2f ms after write\n",
                            SN[st], LN[ld], res[1] ? "SEEN" : "NOT SEEN", res[0], res[2], kData, ms_since(tw));
            } catch (const exception& e) {
                std::printf("%-11s load %-18s: threw %s\n", SN[st], LN[ld], e.what());
                return 2;
            }
            std::fflush(stdout);
        }
    free(base, ctx);
    free(res, ctx);
    return 0;
}
