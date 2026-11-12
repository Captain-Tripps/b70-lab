"""Prepare an isolated opt-in exact-shape Q6_K/BF16 mixed projection prototype."""
import hashlib
import pathlib
import shutil

root = pathlib.Path(r'D:\maya-sycl\experiments')
source = root / 'codex-slot-branch-20261112' / 'tree'
dest = root / 'codex-decode-fusion-audit-20261112' / 'fused-tree'
if dest.exists():
    raise SystemExit('Refusing to overwrite fused tree')
shutil.copytree(source, dest)
p = dest / 'src' / 'kernels' / 'cuda' / 'glm_fast.dp.cpp'
original = p.read_bytes().decode('utf8')
kernel = '''// Exact-shape experiment: one dispatch, retaining the specialized Q6 dot product.
__dpct_inline__ void mv_kernel_q6_bf16(const STRATA_GRID_CONSTANT MvBatch b) {
    auto item_ct1 = sycl::ext::oneapi::this_work_item::get_nd_item<3>();
    if (b.skip != nullptr && *b.skip) return;
    const int bid = item_ct1.get_group(2);
    int ji = 0;
    while (ji < b.n - 1 && bid >= b.blk_end[ji]) ++ji;
    const MvJob& J = b.j[ji];
    const int blk0 = ji ? b.blk_end[ji - 1] : 0;
    const int row = (bid - blk0) * MV_ROWS + (item_ct1.get_local_id(2) >> 5);
    const int lane = item_ct1.get_local_id(2) & 31;
    if (row >= J.n_out) return;
    const float sum = J.type == 14
        ? row_dot<14>((const uint8_t*) J.w + (size_t) row * rbytes<14>(J.n_in),
                      (const block_q8_1*) J.xq, J.n_in, lane)
        : row_dot_bf16((const uint16_t*) J.w + (size_t) row * J.n_in, J.xf, J.n_in, lane);
    if (lane == 0) J.y[row] = mv_out(J.alpha, sum, J.bias ? J.bias[row] : 0.0f);
}

'''
needle = '__dpct_inline__ void mv_kernel(const STRATA_GRID_CONSTANT MvBatch b) {'
if original.count(needle) != 1:
    raise RuntimeError('kernel insertion point changed')
text = original.replace(needle, kernel + needle, 1)
needle = '''    if (!mv_inputs_ok(jobs, n, "mv")) return false;
    // the jobs of the common dense types'''
replacement = '''    if (!mv_inputs_ok(jobs, n, "mv")) return false;
    // Gate on every observed shape and keep all other paths unchanged.
    static const bool q6_bf16_fused = maya_env("MAYA_MV_Q6_BF16_FUSED") != nullptr;
    bool exact_kda = q6_bf16_fused && n == 6 && maya_env("STRATA_GLM_MV_GENERIC") == nullptr;
    for (int i = 0; exact_kda && i < n; ++i) {
        const int want_type = i < 3 ? 14 : kTypeBF16;
        const int want_out = i < 3 ? 8192 : i < 5 ? 128 : 64;
        exact_kda = jobs[i].type == want_type && jobs[i].n_in == 4096 &&
                    jobs[i].n_out == want_out && jobs[i].ncol == 1;
    }
    if (exact_kda) {
        static std::atomic<bool> reported{false};
        if (!reported.exchange(true)) std::fprintf(stderr, "MAYA_MV_Q6_BF16_FUSED active\\n");
        MvBatch b{}; b.skip = g_skip; int acc = 0;
        for (int i = 0; i < n; ++i) {
            b.j[i] = jobs[i]; acc += (jobs[i].n_out + MV_ROWS - 1) / MV_ROWS;
            b.blk_end[i] = acc;
        }
        b.n = n;
        auto exp_props = sycl::ext::oneapi::experimental::properties{
            sycl::ext::oneapi::experimental::use_root_sync};
        s->parallel_for(sycl::nd_range<3>(sycl::range(1, 1, acc) * sycl::range(1, 1, 256),
                                          sycl::range(1, 1, 256)), exp_props,
            [=](sycl::nd_item<3> item_ct1) [[sycl::reqd_sub_group_size(32)]] {
                mv_kernel_q6_bf16(b);
            });
        launch_check("mv_q6_bf16_fused");
        return true;
    }
    // the jobs of the common dense types'''
if text.count(needle) != 1:
    raise RuntimeError('dispatch insertion point changed')
text = text.replace(needle, replacement, 1)
p.write_bytes(text.encode('utf8'))
print('original_sha256', hashlib.sha256(original.encode()).hexdigest())
print('fused_source_sha256', hashlib.sha256(p.read_bytes()).hexdigest())
print('tree', dest)
