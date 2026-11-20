"""GLM r3 (STRATA_GLM_MV_AL16=1): the aligned one-column Q6_K GEMV on 16-lane sub-groups. Lane l does mv_q6_al_kernel's
lanes l and l + 16 (their k sequences summed apart, in order) and folds warp_sum's xor-16 step in-lane, so every row's
sum is mv_q6_al_kernel's bit for bit. Default off. usage: glm_r3_al16.py <glm_fast.dp.cpp>"""
import sys, pathlib
p = pathlib.Path(sys.argv[1]); s = p.read_text(encoding='utf-8')
if 'mv_q6_al16_kernel' in s: sys.exit('already patched')
KERNEL = r'''
#if !defined(STRATA_USE_HIP)
// r3: mv_q6_al_kernel on 16-lane sub-groups (STRATA_GLM_MV_AL16=1).  Lane l does lanes l and l + 16 of the 32-lane
// kernel - their k sequences summed apart, each in its order - and folds warp_sum's xor-16 step in-lane (s0 + s1, as
// lane 0's v + xor16(v)), then the xor 8 / 4 / 2 / 1 steps: every row's sum is mv_q6_al_kernel's bit for bit.
// 16 sub-groups a 256-wide block: 2 * MV_ROWS * R rows a block.
template <int R>
__dpct_inline__ void mv_q6_al16_kernel(const STRATA_GRID_CONSTANT MvBatch b) {
    auto item_ct1 = sycl::ext::oneapi::this_work_item::get_nd_item<3>();
    if (b.skip != nullptr && *b.skip) return;
    const int bid = item_ct1.get_group(2);
    int ji = 0;
    while (ji < b.n - 1 && bid >= b.blk_end[ji]) ++ji;
    const MvJob& J = b.j[ji];
    const int blk0 = ji ? b.blk_end[ji - 1] : 0;
    const int row0 = ((bid - blk0) * (2 * MV_ROWS) + (item_ct1.get_local_id(2) >> 4)) * R;
    const int lane = item_ct1.get_local_id(2) & 15;
    if (row0 >= J.n_out) return;
    const size_t rb = rbytes<14>(J.n_in);
    const block_q8_1* xq = (const block_q8_1*) J.xq;
    const int nb = J.n_in / 256;
    float s[2][R];
#pragma unroll
    for (int h = 0; h < 2; ++h)
#pragma unroll
        for (int r = 0; r < R; ++r) s[h][r] = 0.0f;
    for (int k0 = lane; k0 < nb * 32; k0 += 32) {
#pragma unroll
        for (int h = 0; h < 2; ++h) {
            const int k = k0 + 16 * h;
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
                const float t = sycl::vec<sycl::half, 1>(w->d).convert<float, sycl::rounding_mode::automatic>()[0] * sumf;
                s[h][r] += t;
            }
        }
    }
    const sycl::sub_group sg = item_ct1.get_sub_group();
#pragma unroll
    for (int r = 0; r < R; ++r) {
        float v = s[0][r];
        v += s[1][r];
#pragma unroll
        for (int o = 8; o > 0; o >>= 1) v += sycl::permute_group_by_xor(sg, v, o);
        if (lane == 0 && row0 + r < J.n_out) J.y[row0 + r] = mv_out(J.alpha, v, J.bias ? J.bias[row0 + r] : 0.0f);
    }
}
#endif
static bool q6_al16_on() {
    static const bool on = [] { const char* v = maya_env("STRATA_GLM_MV_AL16"); return v != nullptr && std::atoi(v) != 0; }();
    return on;
}
'''
A = 'int q6_al_mode() {'
assert s.count(A) == 1; s = s.replace(A, KERNEL.lstrip('\n') + A)
B = '            const int per = MV_ROWS * (pr > 0 ? pr : al > 0 ? al : 1);'
assert s.count(B) == 1
s = s.replace(B, '            const bool al16 = al > 0 && q6_al16_on();\n'
                 '            const int per = (al16 ? 2 : 1) * MV_ROWS * (pr > 0 ? pr : al > 0 ? al : 1);')
C = '''            if (al > 0) {
                auto exp_props = sycl::ext::oneapi::experimental::properties{
                    sycl::ext::oneapi::experimental::use_root_sync};
'''
assert s.count(C) == 1
s = s.replace(C, C + '''                if (al16) {
                    if (al == 2)
                        s->parallel_for(
                            sycl::nd_range<3>(sycl::range(1, 1, acc) * sycl::range(1, 1, 256), sycl::range(1, 1, 256)),
                            exp_props,
                            [=](sycl::nd_item<3> item_ct1) [[sycl::reqd_sub_group_size(16)]] { mv_q6_al16_kernel<2>(b); });
                    else
                        s->parallel_for(
                            sycl::nd_range<3>(sycl::range(1, 1, acc) * sycl::range(1, 1, 256), sycl::range(1, 1, 256)),
                            exp_props,
                            [=](sycl::nd_item<3> item_ct1) [[sycl::reqd_sub_group_size(16)]] { mv_q6_al16_kernel<4>(b); });
                    continue;
                }
''')
p.write_text(s, encoding='utf-8'); print('r3 patched')
