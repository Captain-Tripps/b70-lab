# GLM SYCL port base (v1)

The source tree that the b70-lab GLM-5.3 SYCL engine is built from: Project Maya's GLM-5.3-Flash engine
(v1.1.44 @ `5d20b0e8`, CUDA/HIP), converted to SYCL with Intel's SYCLomatic / dpct, then fixed by hand and by the
numbered fix rounds 1-37 in b70-lab `glm-5.3/sycl-port/tools/` (round 36 reverted). This is the tree as it was on
2026-11-12, before the changes that `recipe/apply_live_chain.py` applies.

Use it with `glm-5.3/sycl-port/recipe/setup.cmd` in https://github.com/Captain-Tripps/b70-lab, which downloads this
archive, checks its sha256 and builds from it.

- `src/`, `include/strata/`, `include/maya_compat.hpp`, `include/strata_win_undefs.h`: derived from Project Maya,
  MIT (`LICENSES/LICENSE`). Maya ships extra licenses for code taken from model reference implementations; they are
  in `LICENSES/` as Maya ships them and apply to the same files they apply to in Maya.
- `include/dpct/`, `include/dpct-2025.1/`: SYCLomatic helper headers from Intel, Apache-2.0 with LLVM exception
  (`include/dpct/LICENSE.TXT`).
- `third_party/ggml/`: ggml headers as converted for the port, MIT (ggml authors).

No NVIDIA headers are included; the CUDA paths that remain are stubs or comments.
