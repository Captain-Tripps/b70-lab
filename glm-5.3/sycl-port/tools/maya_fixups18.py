"""Maya GLM port, round 18: a real device clock for the route kernel's phase profile (STRATA_GLM_ROUTE_PROF=1).
clock64() is maya_compat's stub (reads 0 - the profile printed zeros); inside moe_route_kernel alone it becomes
maya_dev_clock(), the sub-group clock (SPV_KHR_shader_clock; B70 has aspect ext_oneapi_clock_sub_group, ~core clock).
The other clock64() sites keep the stub (some may be timeouts that must not start expiring).  Only read when the
profile is on.  Backups in <raw>/../pre-fix18/.  Idempotent."""
import sys, pathlib, shutil
raw = pathlib.Path(sys.argv[1]); bk = raw.parent / "pre-fix18"; bk.mkdir(exist_ok=True)
HELPER = '''
// SYCL port (fixups18): the sub-group cycle counter for the route kernel's profile (clock64 above stays a stub)
#include <sycl/ext/oneapi/experimental/clock.hpp>
inline long long maya_dev_clock() {
#ifdef __SYCL_DEVICE_ONLY__
    return (long long) sycl::ext::oneapi::experimental::clock<sycl::ext::oneapi::experimental::clock_scope::sub_group>();
#else
    return 0;
#endif
}
'''
c = raw / "include/maya_compat.hpp"
s = c.read_text(encoding="utf-8")
if "maya_dev_clock" not in s:
    shutil.copy(c, bk / "maya_compat.hpp")
    c.write_text(s + HELPER, encoding="utf-8"); print("  helper added")
p = raw / "src/kernels/cuda/glm_fast.dp.cpp"
s = p.read_text(encoding="utf-8", errors="surrogateescape")
a = s.index("__dpct_inline__ void moe_route_kernel(const STRATA_GRID_CONSTANT RouteArgs a)")
b = s.index("__dpct_inline__ void moe_wait_kernel", a)
body = s[a:b]
if "maya_dev_clock" not in body:
    n = body.count("clock64()")
    assert n >= 3, n
    shutil.copy(p, bk / "glm_fast.dp.cpp")
    s = s[:a] + body.replace("clock64()", "maya_dev_clock()") + s[b:]
    p.write_text(s, encoding="utf-8", errors="surrogateescape"); print(f"  route kernel: {n} clock reads")
else: print("  already")
