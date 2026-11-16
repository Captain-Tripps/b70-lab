// dp4a_isa.cpp - does IGC turn dpct's generic dp4a (4 sign-extends + 4 multiply-adds) into the native DP4A
// instruction? Two kernels doing 8 chained dp4a's per item: generic form vs the IGC builtin. Compile offline for
// the B70 and diff the ISA (look for "dp4a" in the generic kernel's dump). Also runs both as a bit-exact check
// when a GPU is selected (--run).
#include <sycl/sycl.hpp>
#include <cstdio>
#include <cstring>
#include <vector>

#ifdef __SYCL_DEVICE_ONLY__
extern "C" SYCL_EXTERNAL int __builtin_IB_dp4a_ss(int c, int a, int b, bool sat);
#endif

static inline int dp4a_generic(int a, int b, int c) {
    auto va = sycl::vec<int, 1>(a).template as<sycl::vec<int8_t, 4>>().template convert<int>();
    auto vb = sycl::vec<int, 1>(b).template as<sycl::vec<int8_t, 4>>().template convert<int>();
    int r = c;
    r += va[0] * vb[0];
    r += va[1] * vb[1];
    r += va[2] * vb[2];
    r += va[3] * vb[3];
    return r;
}

static inline int dp4a_native(int a, int b, int c) {
#ifdef __SYCL_DEVICE_ONLY__
    return __builtin_IB_dp4a_ss(c, a, b, false);
#else
    return dp4a_generic(a, b, c);
#endif
}

class KGen;
class KNat;

int main(int argc, char** argv) {
    const bool run = argc > 1 && std::strcmp(argv[1], "--run") == 0;
    const size_t n = 1 << 20;
    sycl::queue q(sycl::gpu_selector_v);
    std::printf("device: %s\n", q.get_device().get_info<sycl::info::device::name>().c_str());
    std::vector<int> ha(n * 8), hb(n * 8);
    uint32_t s = 12345;
    for (auto& v : ha) { s = s * 1664525u + 1013904223u; v = (int) s; }
    for (auto& v : hb) { s = s * 1664525u + 1013904223u; v = (int) s; }
    int *a = sycl::malloc_device<int>(n * 8, q), *b = sycl::malloc_device<int>(n * 8, q);
    int *o1 = sycl::malloc_device<int>(n, q), *o2 = sycl::malloc_device<int>(n, q);
    q.memcpy(a, ha.data(), n * 32).wait();
    q.memcpy(b, hb.data(), n * 32).wait();
    if (!run) return 0;
    q.parallel_for<KGen>(sycl::range<1>(n), [=](sycl::id<1> i) {
        int acc = 0;
#pragma unroll
        for (int j = 0; j < 8; ++j) acc = dp4a_generic(a[i * 8 + j], b[i * 8 + j], acc);
        o1[i] = acc;
    }).wait();
    q.parallel_for<KNat>(sycl::range<1>(n), [=](sycl::id<1> i) {
        int acc = 0;
#pragma unroll
        for (int j = 0; j < 8; ++j) acc = dp4a_native(a[i * 8 + j], b[i * 8 + j], acc);
        o2[i] = acc;
    }).wait();
    std::vector<int> r1(n), r2(n);
    q.memcpy(r1.data(), o1, n * 4).wait();
    q.memcpy(r2.data(), o2, n * 4).wait();
    size_t bad = 0;
    for (size_t i = 0; i < n; ++i) bad += r1[i] != r2[i];
    std::printf("mismatches: %zu of %zu\n", bad, n);
    return bad != 0;
}
