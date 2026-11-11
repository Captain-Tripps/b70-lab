from pathlib import Path
p=Path(r'<work>\experiments\codex-sub768-diagnosis-20261110\tree\src\core\glm_prefill.dp.cpp')
s=p.read_text(encoding='utf8')
old='''                if (!skip_output) hgemm_q(Ly.out, E, DI, B.out16, DI, mixer, E, tn, 0.0f);'''
new='''                if (!skip_output) {
                    static const bool diag_split_out = getenv("MAYA_DIAG_KDA_OUT_512") != nullptr;
                    if (diag_split_out) {
                        for (int out_t = 0; out_t < tn; out_t += 512) {
                            const int out_n = std::min(512, tn - out_t);
                            hgemm_q(Ly.out, E, DI, B.out16 + (size_t)out_t * DI, DI,
                                    mixer + (size_t)out_t * E, E, out_n, 0.0f);
                        }
                    } else hgemm_q(Ly.out, E, DI, B.out16, DI, mixer, E, tn, 0.0f);
                }'''
assert s.count(old)==1;s=s.replace(old,new);p.write_text(s,encoding='utf8');print('patched')
