"""Patch glm_fast.dp.cpp: one-column Q6_K GEMV with aligned 32-bit loads and R rows a warp (mv_q6_al_kernel).

Layout unchanged.  A 210-byte Q6_K block is 4-aligned or 2 bytes off; each lane's ql / qh ints are read as aligned
words (funnel-shifted when 2 off) instead of two 16-bit loads.  Each row's sum is mv_kernel_t<14>'s, the same calls
in the same order, so the output is bit-exact.  STRATA_GLM_MV_AL=0 turns it off, =2 / =4 forces R.
Usage: python patch_q6al.py <tree root>
"""
import pathlib, sys

p = pathlib.Path(sys.argv[1]) / 'src' / 'kernels' / 'cuda' / 'glm_fast.dp.cpp'
s = p.read_text(encoding='utf-8')
assert 'mv_q6_al_kernel' not in s, 'already patched'

KERNEL = r'''// Xe2 (Arc Pro B70): the one-column Q6_K GEMV with every lane's ql / qh int as an aligned 32-bit load.  A 210-byte
// block is 0-3 bytes off a 4-byte boundary (the same for the whole warp, which takes one block an iteration); get_int_b2's
// two 16-bit loads cost mv_kernel_t<14> ~10% on these cards.  R rows a warp.  Each row's sum is mv_kernel_t<14>'s:
// dot_q6_K's calls in row_dot's order with the same ints and floats.  q6_al_mode: 0 off (STRATA_GLM_MV_AL=0), 2 / 4
// forced R, else 1 (R by the launch's rows).  On a B70, us (mv_kernel_t -> R = 2): 24576 x 4096 173 -> 151,
// 12288 x 4096 88 -> 78, 16384 x 1536 53 -> 45, 4096 x 16384 110 -> 100; the head 154880 x 4096 1033 -> 947 (R = 4).
#if !defined(STRATA_USE_HIP)
__dpct_inline__ int q6_ld_al(const uint8_t *p, int sh) {
    const uint32_t* a = (const uint32_t*) (p - sh);
    if (sh == 0) return (int) a[0];
    return (int) ((a[0] >> (8 * sh)) | (a[1] << (32 - 8 * sh)));
}
template <int R>
__dpct_inline__ void mv_q6_al_kernel(const STRATA_GRID_CONSTANT MvBatch b) {
    auto item_ct1 = sycl::ext::oneapi::this_work_item::get_nd_item<3>();
    if (b.skip != nullptr && *b.skip) return;
    const int bid = item_ct1.get_group(2);
    int ji = 0;
    while (ji < b.n - 1 && bid >= b.blk_end[ji]) ++ji;
    const MvJob& J = b.j[ji];
    const int blk0 = ji ? b.blk_end[ji - 1] : 0;
    const int row0 = ((bid - blk0) * MV_ROWS + (item_ct1.get_local_id(2) >> 5)) * R;
    const int lane = item_ct1.get_local_id(2) & 31;
    if (row0 >= J.n_out) return;
    const size_t rb = rbytes<14>(J.n_in);
    const block_q8_1* xq = (const block_q8_1*) J.xq;
    const int nb = J.n_in / 256;
    float s[R];
#pragma unroll
    for (int r = 0; r < R; ++r) s[r] = 0.0f;
    for (int k = lane; k < nb * 32; k += 32) {
        const int kbx = k / 32, iqs = k % 32;
        const block_q8_1* bq8_1 = xq + kbx * 8;
        const int bq8_offset = 4 * (iqs / 16) + (iqs % 16) / 8;
        const int scale_offset = 8 * (iqs / 16) + (iqs % 16) / 4;
        const int vh_shift = 2 * ((iqs % 16) / 8);
        int u[2];
        float d8[2];
#pragma unroll
        for (int i = 0; i < 2; ++i) {
            u[i] = ((const int*) bq8_1[bq8_offset + 2 * i].qs)[iqs % 8];
            d8[i] = bq8_1[bq8_offset + 2 * i].ds[0];
        }
#pragma unroll
        for (int r = 0; r < R; ++r) {
            const block_q6_K* w = (const block_q6_K*) ((const uint8_t*) J.w + (size_t) sycl::min(row0 + r, J.n_out - 1) * rb) + kbx;
            const int sh = (int) ((uintptr_t) w & 3);
            const int vl = q6_ld_al(w->ql + 4 * iqs, sh);
            const int vh = q6_ld_al(w->qh + 4 * (8 * (iqs / 16) + iqs % 8), sh) >> vh_shift;
            const int8_t* scales = w->scales + scale_offset;
            float sumf = 0.0f;
#pragma unroll
            for (int i = 0; i < 2; ++i) {
                const int sc = scales[4 * i];
                const int vil = (vl >> (4 * i)) & 0x0f0f0f0f;
                const int vih = ((vh >> (4 * i)) << 4) & 0x30303030;
                const int vi = dpct::vectorized_binary<sycl::char4>(vil | vih, 0x20202020, dpct::sub_sat());
                sumf += d8[i] * (strata::dp4a(vi, u[i], 0) * sc);
            }
            // (its own statement: under -fp-model=precise a product is fused only within an expression, and
            // row_dot adds dot_q6_K's returned product unfused)
            const float t = sycl::vec<sycl::half, 1>(w->d).convert<float, sycl::rounding_mode::automatic>()[0] * sumf;
            s[r] += t;
        }
    }
#pragma unroll
    for (int r = 0; r < R; ++r) {
        const float v = warp_sum(s[r]);
        if (lane == 0 && row0 + r < J.n_out) J.y[row0 + r] = mv_out(J.alpha, v, J.bias ? J.bias[row0 + r] : 0.0f);
    }
}
#endif
int q6_al_mode() {
#if defined(STRATA_USE_HIP)
    return 0;
#else
    static int cache = 0;
    if (cache == 0) {
        const char* v = maya_env("STRATA_GLM_MV_AL");
        const int r = v != nullptr ? std::atoi(v) : 1;
        cache = r == 0 ? -1 : (r == 2 || r == 4 ? r : 1);
    }
    return cache > 0 ? cache : 0;
#endif
}

'''
anchor = '// ... BF16 weights against float activations (the routers'
assert s.count(anchor) == 1
s = s.replace(anchor, KERNEL + anchor, 1)

# launch: R for the aligned kernel (when the cc-6.0 one is not taken)
a2 = '            const int per = MV_ROWS * (pr > 0 ? pr : 1);'
assert s.count(a2) == 1
s = s.replace(a2, '''            int al = 0;   // mv_q6_al_kernel's R (0: mv_kernel_t)
#if !defined(STRATA_USE_HIP)
            if (T == 14 && pr == 0) {
                if (const int mode = q6_al_mode(); mode > 0) {
                    int rows = 0;
                    for (int i = 0; i < n; ++i)
                        if (!done[i] && jobs[i].type == T) rows += jobs[i].n_out;
                    al = mode > 1 ? mode : rows >= 65536 ? 4 : rows >= 4096 ? 2 : 0;
                }
            }
#endif
            const int per = MV_ROWS * (pr > 0 ? pr : al > 0 ? al : 1);''', 1)

a3 = '                continue;\n            }\n#endif\n            switch (T) {\n            case 14: {'
assert s.count(a3) == 1
LAUNCH = '''#if !defined(STRATA_USE_HIP)
            if (al > 0) {
                auto exp_props = sycl::ext::oneapi::experimental::properties{
                    sycl::ext::oneapi::experimental::use_root_sync};
                if (al == 2)
                    s->parallel_for(
                        sycl::nd_range<3>(sycl::range(1, 1, acc) * sycl::range(1, 1, 256), sycl::range(1, 1, 256)),
                        exp_props,
                        [=](sycl::nd_item<3> item_ct1) [[sycl::reqd_sub_group_size(32)]] { mv_q6_al_kernel<2>(b); });
                else
                    s->parallel_for(
                        sycl::nd_range<3>(sycl::range(1, 1, acc) * sycl::range(1, 1, 256), sycl::range(1, 1, 256)),
                        exp_props,
                        [=](sycl::nd_item<3> item_ct1) [[sycl::reqd_sub_group_size(32)]] { mv_q6_al_kernel<4>(b); });
                continue;
            }
#endif
'''
s = s.replace(a3, '                continue;\n            }\n#endif\n' + LAUNCH + '            switch (T) {\n            case 14: {', 1)
p.write_text(s, encoding='utf-8', newline='\n')
print('patched', p)
