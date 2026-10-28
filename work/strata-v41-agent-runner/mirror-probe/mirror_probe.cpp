// Host-mirror probe: does device memory on this Windows SYCL / Level Zero stack cost host RAM,
// and at which step - allocation, device-side write, or host->device copy?
//
// usage: mirror_probe <sycl|ze> <pageable|pinned> <GiB> <gpu-index>
// Prints, after each step: process private bytes, working set, system commit, system available.
#include <sycl/sycl.hpp>
#include <level_zero/ze_api.h>
#include <windows.h>
#include <psapi.h>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <string>
#include <thread>
#include <vector>

static const size_t GiB = 1ull << 30;

static void report(const char *step) {
    std::this_thread::sleep_for(std::chrono::seconds(3));
    PROCESS_MEMORY_COUNTERS_EX pm{};
    GetProcessMemoryInfo(GetCurrentProcess(), (PROCESS_MEMORY_COUNTERS *)&pm, sizeof(pm));
    PERFORMANCE_INFORMATION pi{};
    GetPerformanceInfo(&pi, sizeof(pi));
    double page = (double)pi.PageSize;
    printf("%-34s priv=%7.2f GiB  ws=%7.2f GiB  sys_commit=%7.2f GiB  sys_avail=%7.2f GiB\n", step,
           pm.PrivateUsage / (double)GiB, pm.WorkingSetSize / (double)GiB,
           pi.CommitTotal * page / GiB, pi.PhysicalAvailable * page / GiB);
    fflush(stdout);
}

int main(int argc, char **argv) {
    if (argc < 5) { printf("usage: %s <sycl|ze> <pageable|pinned> <GiB> <gpu-index>\n", argv[0]); return 2; }
    std::string mode = argv[1], src = argv[2];
    int n = atoi(argv[3]), idx = atoi(argv[4]);

    auto gpus = sycl::device::get_devices(sycl::info::device_type::gpu);
    if (idx >= (int)gpus.size()) { printf("only %zu gpus\n", gpus.size()); return 2; }
    sycl::device dev = gpus[idx];
    sycl::context ctx(dev);
    sycl::queue q(ctx, dev, sycl::property::queue::in_order());
    printf("device %d: %s  backend=%d  mode=%s src=%s size=%d GiB\n", idx,
           dev.get_info<sycl::info::device::name>().c_str(), (int)dev.get_backend(), mode.c_str(), src.c_str(), n);
    report("0 baseline (context created)");

    std::vector<void *> chunks(n, nullptr);
    if (mode == "ze") {
        auto zctx = sycl::get_native<sycl::backend::ext_oneapi_level_zero>(ctx);
        auto zdev = sycl::get_native<sycl::backend::ext_oneapi_level_zero>(dev);
        for (int i = 0; i < n; i++) {
            ze_device_mem_alloc_desc_t d{ZE_STRUCTURE_TYPE_DEVICE_MEM_ALLOC_DESC};
            ze_result_t r = zeMemAllocDevice(zctx, &d, GiB, 64, zdev, &chunks[i]);
            if (r != ZE_RESULT_SUCCESS) { printf("zeMemAllocDevice failed at %d: 0x%x\n", i, r); return 1; }
        }
    } else {
        for (int i = 0; i < n; i++) {
            chunks[i] = sycl::malloc_device(GiB, q);
            if (!chunks[i]) { printf("malloc_device failed at %d\n", i); return 1; }
        }
    }
    report("1 after device alloc");

    for (int i = 0; i < n; i++) q.memset(chunks[i], 0x5a, GiB);
    q.wait();
    report("2 after device-side memset");

    const size_t hb = 256ull << 20;
    char *host = src == "pinned" ? (char *)sycl::malloc_host(hb, q) : (char *)malloc(hb);
    memset(host, 0x3c, hb);
    report("3 host staging buffer (256 MiB)");

    for (int i = 0; i < n; i++)
        for (size_t off = 0; off < GiB; off += hb) q.memcpy((char *)chunks[i] + off, host, hb);
    q.wait();
    report("4 after host->device copy");

    if (src == "pinned") sycl::free(host, q); else free(host);
    report("5 host buffer freed");
    std::this_thread::sleep_for(std::chrono::seconds(12));
    report("6 idle 15 s");

    // device->host read-back of one chunk, to see if reads also stage
    std::vector<char> back(hb);
    q.memcpy(back.data(), chunks[0], hb).wait();
    report("7 after 256 MiB device->host read");

    if (mode == "ze") {
        auto zctx = sycl::get_native<sycl::backend::ext_oneapi_level_zero>(ctx);
        for (void *p : chunks) zeMemFree(zctx, p);
    } else {
        for (void *p : chunks) sycl::free(p, q);
    }
    report("8 device memory freed");
    return 0;
}
