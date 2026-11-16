"""Apply the live changes made since the port base (2026-11-12 to 2026-11-16) to a copy of the port base tree, in the
order they went live. Each step is the same script or edit that built the live engine; see RECIPE.md.

usage: python apply_live_chain.py <tree> <llama.cpp PR checkout> [--check <ref root>]

  <tree>        a copy of the port base (src/, include/, third_party/), patched in place
  <PR checkout> llama.cpp at refs/pull/31428/head = eec5c09; its ggml/src/ggml-sycl/fused-gemm.hpp is patched in place
                (step 9), so use a checkout of its own
  --check       for each step, compare <tree>/src and <tree>/include with the reference tree named in REFS under
                <ref root> (the trees the live engine was built from); used to verify this script, not needed to build

Every step stops on the first anchor that does not match, so a wrong base fails loudly instead of building something
else."""
import filecmp, pathlib, subprocess, sys

HERE = pathlib.Path(__file__).resolve().parent
EXP = HERE.parent / 'experiments'

argv = [a for a in sys.argv[1:]]
check = None
if '--check' in argv:
    i = argv.index('--check')
    check = pathlib.Path(argv[i + 1])
    del argv[i:i + 2]
if len(argv) != 2:
    sys.exit(__doc__)
tree, pr = pathlib.Path(argv[0]).resolve(), pathlib.Path(argv[1]).resolve()
prs = pr / 'ggml' / 'src' / 'ggml-sycl'
fx = tree / 'src' / 'forkxmx'
for p in (tree / 'src' / 'program' / 'generate.cpp', fx / 'maya_fg_shim.cpp', prs / 'fused-gemm-esimd.cpp'):
    if not p.exists():
        sys.exit('missing ' + str(p))

# reference trees on the build machine, relative to <ref root> (the engine's experiments folder)
REFS = {
    1: 'codex-slot-branch-20261112/tree',
    2: 'codex-glm-ckpt-carry-20261113/tree',
    3: 'codex-glm-ckpt-resume-20261113/tree',
    4: 'codex-glm-slot-reuse-v3-20261113/tree',
    5: 'claude-glm-q6al-20261114/tree',
    6: 'claude-glm-l12-20261115/tree',
    7: 'claude-glm-l12-20261115/tree2',
    8: 'claude-glm-l12-20261115/tree4',
    9: 'claude-glm-l12-20261115/tile-m32-n64',
}


def run(*cmd):
    r = subprocess.run([str(c) for c in cmd])
    if r.returncode:
        sys.exit('failed: ' + ' '.join(str(c) for c in cmd))


def py(script, *args):
    run(sys.executable, EXP / script, *args)


def diff_tree(a, b):
    """files that differ or exist on one side only, under src/ and include/"""
    out = []
    for sub in ('src', 'include'):
        stack = [filecmp.dircmp(a / sub, b / sub)]
        while stack:
            d = stack.pop()
            out += [str(pathlib.Path(d.left) / f) for f in d.left_only + d.right_only + d.funny_files]
            _, mism, errs = filecmp.cmpfiles(d.left, d.right, d.common_files, shallow=False)
            out += [str(pathlib.Path(d.left) / f) for f in mism + errs]
            stack += d.subdirs.values()
    return out


def done(n, what):
    msg = 'step %d %s' % (n, what)
    if check is not None:
        bad = diff_tree(tree, check / REFS[n])
        msg += ': ' + ('same as ' + REFS[n] if not bad else '%d DIFFER: %s' % (len(bad), ' '.join(bad[:6])))
    print(msg, flush=True)


def edit(path, old, new, count=1):
    b = path.read_bytes()
    s = b.decode('utf-8')
    if s.count(old) != count:
        sys.exit('%s: expected %d of %r, found %d' % (path, count, old[:60], s.count(old)))
    path.write_bytes(s.replace(old, new).encode('utf-8'))


# 1. 2026-11-12 keep a shorter RAM slot as a branch (STRATA_GLM_SLOT_KEEP_BRANCH)
r = subprocess.run(['git', 'apply', '-p1', '--whitespace=nowarn', str(EXP / '2026-11-12-slot-branches' / 'branch-preserve.patch')],
                   cwd=tree)
if r.returncode:
    sys.exit('step 1: branch-preserve.patch did not apply')
done(1, 'slot branch preserve')
# 2-4. 2026-11-13 slot checkpoint carry, resume, buffer reuse (STRATA_GLM_SLOT_CARRY_CKPT / _CKPT_RESUME / _REUSE)
py('2026-11-13-slot-carry-ckpt/patch_ckpt_carry.py', tree); done(2, 'slot checkpoint carry')
py('2026-11-13-slot-ckpt-resume/patch_ckpt_resume.py', tree); done(3, 'slot checkpoint resume')
py('2026-11-13-slot-buffer-reuse/patch_slot_reuse.py', tree); done(4, 'slot buffer reuse')
# 5. 2026-11-14 aligned-load Q6_K mat-vec
py('2026-11-14-q6k-aligned-gemv/patch_q6al.py', tree); done(5, 'Q6_K aligned GEMV')

# 6. 2026-11-16 L12: llama.cpp#31428's grouped GEMM (ESIMD) in place of the fork's, shim moved to its API
for f in ('fused-gemm.cpp', 'fused-gemm-esimd.cpp'):
    (fx / f).write_bytes((prs / f).read_bytes())
shim = fx / 'maya_fg_shim.cpp'
s = shim.read_text(encoding='utf-8')
s = s.replace('ggml_sycl_gg_tile', 'ggml_sycl_grouped_gemm_tile')
s = s.replace('x, GGML_PREC_DEFAULT, dst', 'x, GGML_PREC_UNDEFINED, dst')
if 'g_ggml_sycl_mmid_sched' not in s:
    s = s.replace('int g_ggml_sycl_dynamic_required_precision',
                  'int g_ggml_sycl_mmid_sched = GGML_SYCL_MMID_SCHED_DEVICE;   // read only by the device-scheduled entry\n'
                  'int g_ggml_sycl_dynamic_required_precision')
if 'int ggml_sycl_get_env(' not in s:
    s = s.replace('extern "C" int maya_fg_type_ok(int type) {',
                  'int ggml_sycl_get_env(const char* name, int default_val) { return env_int(name, default_val); }\n\n'
                  'extern "C" int maya_fg_type_ok(int type) {')
shim.write_text(s, encoding='utf-8', newline='\n')
done(6, 'L12 ESIMD grouped GEMM')

# 7. 2026-11-16 IQ2_S format for the ESIMD kernel
(fx / 'fused-gemm-esimd.cpp').write_bytes((prs / 'fused-gemm-esimd.cpp').read_bytes())
py('2026-11-15-esimd-grouped-gemm/patch_iq2s.py', fx, prs, EXP / '2026-11-15-esimd-grouped-gemm' / 'iq2s_code_table.inc')
done(7, 'IQ2_S ESIMD loader')
# 8. 2026-11-16 L5 XMX prompt indexer (STRATA_GLM_DSA_XMX)
py('2026-11-16-indexer-xmx/patch_dsa.py', tree); done(8, 'L5 XMX indexer')

# 9. 2026-11-16 L14 64-wide tiles: the PR header takes the tile width from MAYA_FG_BN (32 when unset)
hdr = prs / 'fused-gemm.hpp'
if 'MAYA_FG_BN' not in hdr.read_text(encoding='utf-8'):
    edit(hdr, 'static constexpr int GGML_SYCL_FG_BN = 32;',
         '#ifndef MAYA_FG_BN\n#define MAYA_FG_BN 32\n#endif\nstatic constexpr int GGML_SYCL_FG_BN = MAYA_FG_BN;')
for name in ('fused-gemm.cpp', 'fused-gemm-esimd.cpp', 'maya_fg_shim.cpp'):
    p = fx / name
    s = p.read_text(encoding='utf-8')
    s = '#define MAYA_FG_BN %d   // L14 tile sweep\n' % 64 + s
    if name == 'fused-gemm.cpp':
        old = 'static constexpr int BN      = TN > 32 ? TN : 32;'
        if s.count(old) != 1:
            sys.exit('step 9: BN line not found in ' + name)
        s = s.replace(old, 'static constexpr int BN      = TN > GGML_SYCL_FG_BN ? TN : GGML_SYCL_FG_BN;')
    if name == 'fused-gemm-esimd.cpp':
        old = 'static constexpr int GROUPED_GEMM_MR               = 32;'
        if s.count(old) != 1:
            sys.exit('step 9: MR line not found in ' + name)
    p.write_text(s, encoding='utf-8', newline='\n')
done(9, 'L14 64-wide ESIMD tiles')
print('LIVE_CHAIN_APPLIED', tree)
