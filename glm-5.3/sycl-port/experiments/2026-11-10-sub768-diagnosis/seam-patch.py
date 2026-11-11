from pathlib import Path
p=Path(r'<work>\experiments\codex-sub768-diagnosis-20261110\tree\src\core\glm_prefill.dp.cpp')
s=p.read_text(encoding='utf8')
old='''                const float* pr[3] = {B.proj[0], B.proj[1], B.proj[2]};'''
new='''                if (il == 0 && t0 + tn == T) {
                    dump_row("kda_q-0", B.proj[0], DI, tn - 1);
                    dump_row("kda_k-0", B.proj[1], DI, tn - 1);
                    dump_row("kda_v-0", B.proj[2], DI, tn - 1);
                    dump_row("kda_fa-0", B.fa, HD, tn - 1);
                    dump_row("kda_ga-0", B.ga, HD, tn - 1);
                    dump_row("kda_beta-0", B.beta, g.n_head, tn - 1);
                }
''' + old
assert s.count(old)==1;s=s.replace(old,new)
old='''                S->mark("kda_proj", s);'''
new='''                if (il == 0 && t0 + tn == T) {
                    dump_row("kda_cq-0", B.conv[0], DI, tn - 1);
                    dump_row("kda_ck-0", B.conv[1], DI, tn - 1);
                    dump_row("kda_cv-0", B.conv[2], DI, tn - 1);
                    dump_row("kda_g1-0", B.g1, DI, tn - 1);
                    dump_row("kda_g2-0", B.g2, DI, tn - 1);
                }
''' + old
assert s.count(old)==1;s=s.replace(old,new)
old='''                S->mark("kda_rec", s);'''
new='''                if (il == 0 && t0 + tn == T && cb_dir && cb_dir[0]) {
                    s->wait();
                    std::vector<sycl::half> buf((size_t) DI);
                    dpct::get_in_order_queue().memcpy(buf.data(), B.out16 + (size_t)(tn - 1) * DI, (size_t)DI * sizeof(sycl::half)).wait();
                    if (FILE* f = std::fopen((std::string(cb_dir) + "/kda_out16-0.f16").c_str(), "wb")) {
                        std::fwrite(buf.data(), sizeof(sycl::half), buf.size(), f);
                        std::fclose(f);
                    }
                }
''' + old
assert s.count(old)==1;s=s.replace(old,new)
p.write_text(s,encoding='utf8')
print('patched',p)
