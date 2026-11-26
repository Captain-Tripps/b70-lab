// ctxx: can a kernel in a per-device context use USM allocated in the default (platform) context?
// Cases on device 1 (own context): read/write default-ctx device memory on dev 1, default-ctx host memory,
// default-ctx device memory on dev 0 (peer). Each checked by value.
#include <sycl/sycl.hpp>
#include <cstdio>
#include <vector>
int main() {
    auto gpus = sycl::device::get_devices(sycl::info::device_type::gpu);
    if (gpus.size() < 2) { std::printf("need 2 GPUs\n"); return 1; }
    sycl::queue d0(gpus[0], sycl::property::queue::in_order());   // default context
    sycl::queue d1(gpus[1], sycl::property::queue::in_order());   // default context
    std::printf("default ctx shared: %d\n", (int) (d0.get_context() == d1.get_context()));
    sycl::queue o1(sycl::context(gpus[1]), gpus[1], sycl::property::queue::in_order());   // own context
    const int n = 1024;
    int* dev1 = sycl::malloc_device<int>(n, d1);
    int* dev0 = sycl::malloc_device<int>(n, d0);
    int* host = sycl::malloc_host<int>(n, d0);
    struct C { const char* name; int* p; sycl::queue* back; };
    C cs[3] = {{"default-ctx device mem, same card", dev1, &d1}, {"default-ctx host mem", host, &d0}, {"default-ctx device mem, peer card", dev0, &d0}};
    for (auto& c : cs) {
        try {
            c.back->fill(c.p, 7, n).wait();
            int* p = c.p;
            o1.parallel_for(sycl::range<1>(n), [=](sycl::id<1> i) { p[i] = p[i] * 3 + (int) i[0]; }).wait();
            std::vector<int> h(n);
            c.back->memcpy(h.data(), c.p, n * sizeof(int)).wait();
            int bad = 0; for (int i = 0; i < n; ++i) bad += h[i] != 21 + i;
            std::printf("%-36s : %s (%d bad)\n", c.name, bad ? "WRONG" : "ok", bad);
        } catch (const std::exception& e) { std::printf("%-36s : EXCEPTION %s\n", c.name, e.what()); }
        std::fflush(stdout);
    }
    return 0;
}
