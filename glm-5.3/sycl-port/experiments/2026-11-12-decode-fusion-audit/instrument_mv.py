"""Prepare a separate copied source tree with opt-in, bounded host dispatch tracing."""
import hashlib
import pathlib
import shutil

root = pathlib.Path(r'D:\maya-sycl\experiments')
source = root / 'codex-slot-branch-20261112' / 'tree'
dest = root / 'codex-decode-fusion-audit-20261112' / 'instrumented-tree'
if dest.exists():
    raise SystemExit('Refusing to overwrite instrumented tree')
shutil.copytree(source, dest)
p = dest / 'src' / 'kernels' / 'cuda' / 'glm_fast.dp.cpp'
original = p.read_bytes().decode('utf8')
start = original.index('bool mv(const MvJob *jobs, int n, dpct::queue_ptr s) {')
end = original.index('\nnamespace {\ntemplate <int NT>\nvoid mv_nt_launch', start)
block = original[start:end]

def replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError('expected exactly one insertion point')
    return text.replace(old, new, 1)

block = replace_once(block, '    // one column\n    if (typed) {', '''    // Diagnostic: only six-job, single-column calls; collect actual dispatches below.
    static const bool audit_enabled = maya_env("MAYA_MV_AUDIT") != nullptr;
    static std::atomic<int> audit_samples{0};
    bool audit_one_col = n == 6;
    for (int i = 0; i < n; ++i) audit_one_col = audit_one_col && jobs[i].ncol == 1;
    const bool audit = audit_enabled && audit_one_col && audit_samples.fetch_add(1) < 64;
    int audit_typed_launches = 0, audit_generic_launches = 0;
    // one column
    if (typed) {''')
block = replace_once(block, '''            if (m == 0) continue;
            b.n = m;
#if !defined(STRATA_USE_HIP)
            if (pr > 0) {''', '''            if (m == 0) continue;
            if (audit) ++audit_typed_launches;
            b.n = m;
#if !defined(STRATA_USE_HIP)
            if (pr > 0) {''')
needle = '''    if (m > 0) {
        b.n = m;
        {
            auto exp_props = sycl::ext::oneapi::experimental::properties{'''
pos = block.rfind(needle)
if pos < 0:
    raise RuntimeError('generic insertion point missing')
block = block[:pos] + block[pos:].replace(needle, needle.replace('        b.n = m;', '        if (audit) ++audit_generic_launches;\n        b.n = m;'), 1)
block = replace_once(block, '    launch_check("mv");\n    return true;', '''    if (audit) {
        char details[512]; int at = 0;
        for (int i = 0; i < n && at < (int)sizeof(details) - 64; ++i)
            at += std::snprintf(details + at, sizeof(details) - at, " %d:%d:%d:%d",
                                jobs[i].type, jobs[i].n_in, jobs[i].n_out, jobs[i].ncol);
        std::fprintf(stderr, "MAYA_MV_AUDIT typed=%d generic=%d jobs=%d%s\\n",
                     audit_typed_launches, audit_generic_launches, n, details);
    }
    launch_check("mv");
    return true;''')
p.write_bytes((original[:start] + block + original[end:]).encode('utf8'))
print('source_sha256', hashlib.sha256(original.encode()).hexdigest())
print('instrumented_sha256', hashlib.sha256(p.read_bytes()).hexdigest())
print('tree', dest)
