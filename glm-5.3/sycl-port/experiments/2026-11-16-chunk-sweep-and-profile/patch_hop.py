"""L16 hop probe: route the pipelined prompt read's two hand-off copies (part k -> its pinned host slot, slot -> part
k + 1) through glm_hop_copy. Default behaviour is the old maya_kcopy, unchanged.
STRATA_GLM_HOP_TIME=1: drain the queue, copy, drain again, log the copy's host-measured time.
STRATA_GLM_HOP_VEC=1: copy 16 bytes a work-item instead of 4.
usage: patch_hop.py <tree>"""
import pathlib, re, sys
p = pathlib.Path(sys.argv[1]) / 'src' / 'core' / 'glm_prefill.dp.cpp'
s = p.read_text(encoding='utf-8')
assert 'glm_hop_copy' not in s

helper = r'''
// L16 hop probe (2026-11-16): STRATA_GLM_HOP_TIME=1 times each prompt hop copy on the host (queue drained before and
// after); STRATA_GLM_HOP_VEC=1 copies 16 bytes a work-item. Neither changes a bit of the copied data.
static sycl::event glm_hop_copy(sycl::queue* q, void* dst, const void* src, size_t bytes, int part, int chunk,
                                const char* dir) {
    static const bool tm = std::getenv("STRATA_GLM_HOP_TIME") != nullptr;
    static const bool vec = std::getenv("STRATA_GLM_HOP_VEC") != nullptr;
    std::chrono::steady_clock::time_point t0;
    if (tm) {
        q->wait();
        t0 = std::chrono::steady_clock::now();
    }
    sycl::event ev;
    if (vec && bytes % 16 == 0 && (uintptr_t) dst % 16 == 0 && (uintptr_t) src % 16 == 0) {
        sycl::uint4* d = (sycl::uint4*) dst;
        const sycl::uint4* sp = (const sycl::uint4*) src;
        ev = q->parallel_for(sycl::range<1>(bytes / 16), [=](sycl::id<1> i) { d[i] = sp[i]; });
    } else {
        ev = maya_kcopy(q, dst, src, bytes);
    }
    if (tm) {
        q->wait();
        const double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
        std::fprintf(stderr, "glm hop probe: part %d chunk %d %s %zu bytes %.3f ms\n", part, chunk, dir, bytes, ms);
    }
    return ev;
}
'''
anchor = '#include <dpct/lib_common_utils.hpp>\n'
assert s.count(anchor) == 1
s = s.replace(anchor, anchor + helper, 1)

out_re = re.compile(r'maya_kcopy\(m->fast_->cs,\s*m->pf_->hop_h \+ \(size_t\)\(c & 1\) \* slot,\s*m->pf_->R,\s*'
                    r'\(size_t\)T \* 4 \* E \* sizeof\(float\)\);')
in_re = re.compile(r'maya_kcopy\(m->fast_->cs,\s*m->pf_->R,\s*up->pf_->hop_h \+ \(size_t\)\(c & 1\) \* slot,\s*'
                   r'\(size_t\)T \* 4 \* E \* sizeof\(float\)\);')
assert len(out_re.findall(s)) == 1, out_re.findall(s)
assert len(in_re.findall(s)) == 1, in_re.findall(s)
s = out_re.sub('glm_hop_copy(m->fast_->cs, m->pf_->hop_h + (size_t)(c & 1) * slot, m->pf_->R, '
               '(size_t)T * 4 * E * sizeof(float), k, c, "out");', s)
s = in_re.sub('glm_hop_copy(m->fast_->cs, m->pf_->R, up->pf_->hop_h + (size_t)(c & 1) * slot, '
              '(size_t)T * 4 * E * sizeof(float), k, c, "in");', s)
p.write_text(s, encoding='utf-8', newline='\n')
print('patched', p, s.count('glm_hop_copy('))
