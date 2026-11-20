"""GLM r1: the expert gate/up kernel (glmf::moe_gate_up_kernel, spills 4352-5760 B a thread on the live build, VTune
2026-11-14) with 256 registers, STRATA_GLM_GU_GRF=1 (default 0 = the live launch). Register allocation only: the same
ops in the same order, so the same bits. The 256-register launch also leaves out use_root_sync.
usage: python glm_r1_gugrf.py <tree>/src/kernels/cuda/glm_fast.dp.cpp"""
import sys, pathlib
p = pathlib.Path(sys.argv[1])
t = p.read_text(encoding="utf-8")

inc_old = '#include "ggml-common.h"\n'
inc_new = inc_old + '''#include <sycl/ext/intel/experimental/grf_size_properties.hpp>   // r1
// r1: STRATA_GLM_GU_GRF=1 - the expert gate/up kernel with 256 registers (default 0)
static inline bool glm_gu_grf() {
    static const bool on = [] { const char* e = std::getenv("STRATA_GLM_GU_GRF"); return e != nullptr && std::atoi(e) == 1; }();
    return on;
}
'''

old = r'''            cgh.parallel_for(         \
                sycl::nd_range<3>(grid * sycl::range(1, 1, GU_WARPS * 32),     \
                                  sycl::range(1, 1, GU_WARPS * 32)),           \
                exp_props,                                                     \
                [=](sycl::nd_item<3> item_ct1)                                 \
                    [[sycl::reqd_sub_group_size(32)]] {                        \
                        moe_gate_up_kernel<T>(                                 \
                            d_ct0, kk_ct1, n_embd_ct2, n_ff_ct3, limit_ct4,    \
                            X_ct5, H_ct6, SD_ct7, sh_type_ct8, SH_ct9,         \
                            n_ff_sh_ct10, sh_out_ct11);     \
                    });                                                        \
        });                                                                    ''' + "\\"
new = r'''            const auto nr_gu = sycl::nd_range<3>(grid * sycl::range(1, 1, GU_WARPS * 32), \
                                                 sycl::range(1, 1, GU_WARPS * 32));            \
            if (glm_gu_grf()) {   /* r1: 256 registers (its own kernel name) */                \
                cgh.parallel_for(nr_gu,                                                     \
                    sycl::ext::oneapi::experimental::properties{                            \
                        sycl::ext::intel::experimental::grf_size<256>},                     \
                    [=](sycl::nd_item<3> item_ct1) [[sycl::reqd_sub_group_size(32)]] {      \
                        moe_gate_up_kernel<T>(d_ct0, kk_ct1, n_embd_ct2, n_ff_ct3,         \
                            limit_ct4, X_ct5, H_ct6, SD_ct7, sh_type_ct8, SH_ct9,          \
                            n_ff_sh_ct10, sh_out_ct11);                                     \
                    });                                                                     \
            } else                                                                          \
            cgh.parallel_for(         \
                nr_gu,                                                         \
                exp_props,                                                     \
                [=](sycl::nd_item<3> item_ct1)                                 \
                    [[sycl::reqd_sub_group_size(32)]] {                        \
                        moe_gate_up_kernel<T>(                                 \
                            d_ct0, kk_ct1, n_embd_ct2, n_ff_ct3, limit_ct4,    \
                            X_ct5, H_ct6, SD_ct7, sh_type_ct8, SH_ct9,         \
                            n_ff_sh_ct10, sh_out_ct11);     \
                    });                                                        \
        });                                                                    ''' + "\\"
for o, n, what in ((inc_old, inc_new, "include"), (old, new, "GLMF_GU launch")):
    if t.count(o) != 1:
        sys.exit(f"r1: {what} anchor found {t.count(o)} times, want 1")
    t = t.replace(o, n)
p.write_text(t, encoding="utf-8", newline="")
print("r1 patched")
