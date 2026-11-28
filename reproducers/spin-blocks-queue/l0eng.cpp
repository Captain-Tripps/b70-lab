// l0eng: the Level Zero command queue groups (engines) of each GPU, and which ordinal/index SYCL queues use.
#include <level_zero/ze_api.h>
#include <sycl/sycl.hpp>
#include <sycl/ext/oneapi/backend/level_zero.hpp>
#include <windows.h>
#include <cstdio>
#include <vector>
int main() {
    HMODULE h = LoadLibraryA("ze_loader.dll");
    auto pGroups = (decltype(&zeDeviceGetCommandQueueGroupProperties)) GetProcAddress(h, "zeDeviceGetCommandQueueGroupProperties");
    auto gpus = sycl::device::get_devices(sycl::info::device_type::gpu);
    for (size_t g = 0; g < gpus.size(); ++g) {
        ze_device_handle_t zd = sycl::get_native<sycl::backend::ext_oneapi_level_zero>(gpus[g]);
        uint32_t n = 0;
        pGroups(zd, &n, nullptr);
        std::vector<ze_command_queue_group_properties_t> p(n);
        for (auto& x : p) { x = {}; x.stype = ZE_STRUCTURE_TYPE_COMMAND_QUEUE_GROUP_PROPERTIES; }
        pGroups(zd, &n, p.data());
        std::printf("GPU %zu %s: %u groups\n", g, gpus[g].get_info<sycl::info::device::name>().c_str(), n);
        for (uint32_t i = 0; i < n; ++i)
            std::printf("  ordinal %u: %u queues, flags%s%s%s\n", i, p[i].numQueues,
                        (p[i].flags & ZE_COMMAND_QUEUE_GROUP_PROPERTY_FLAG_COMPUTE) ? " COMPUTE" : "",
                        (p[i].flags & ZE_COMMAND_QUEUE_GROUP_PROPERTY_FLAG_COPY) ? " COPY" : "",
                        (p[i].flags & ZE_COMMAND_QUEUE_GROUP_PROPERTY_FLAG_COOPERATIVE_KERNELS) ? " COOP" : "");
        if (g == 0) break;
    }
    return 0;
}
