# MTP / DSpark draft head - DeepSeek-V4.1-Flash-1017

Pre-commit gating check for option A' (Maya `ds4` SYCL port), 2026-11-16.
Scope: does a usable drafter exist for 1017, where does it live, and how does the
ds4 engine load it? No builds, no downloads beyond the index/README/manifest fetches noted below.

**Verdict: the gating risk is cleared.** The original checkpoint ships a 3-block
DSpark drafter (`mtp.*`, 2,401 tensors), the official Maya packs ship it as separate
4.3-8.0 GB files, the ds4 engine has first-class drafter support (`--dspark on|off|none`,
`--dspark-conf F`, cost-aware window, per-position accept stats), and the lab's live
GLM SYCL port already runs an MTP draft stage on 4 Arc cards in production.

## 1. The original checkpoint ships the drafter

Source: `deepseek-ai/DeepSeek-V4.1-Flash-1017`, `model.safetensors.index.json`
(downloaded to `%TEMP%\ds1017-index.json`) + `config.json` (`%TEMP%\ds1017-config.json`).

- 96,085 tensors total; **2,401 `mtp.*`** (zero `dspark.*`, `nextn.*`, `draft.*` - the
  checkpoint uses plain `mtp.<i>` naming).
- `mtp.0` = 801 tensors, `mtp.1` = 798, `mtp.2` = 802 - three MTP blocks, each with
  attn (13), ffn (777 = 128 routed experts x 3 weights + dense), `hc_*` hyper-connection
  tensors, `main_norm`, `main_proj`.
- `config.json` text_config: `num_nextn_predict_layers: 3`, `dspark_block_size: 5`,
  `dspark_target_layer_ids: [37, 38, 39]`, `dspark_markov_rank: 256`,
  `dspark_n_routed_experts: 128`. So DSpark = 3 draft blocks, block size 5, reading
  trunk layers 37-39, with a rank-256 Markov head and 128 routed experts per block.

The 11-12 placement-sweep note "DSpark drafter for 1017 still absent (zero `mtp.*`)"
refers to the **lab's llama.cpp 1017 pack** (the on-disk GSQ-RCO IQ2_XXS + Engram),
not the original checkpoint. It is still true of that pack: option B (llama.cpp yardstick)
runs 1017 with no drafter unless the pack is rebuilt with `mtp.*` included.

## 2. The official Maya packs ship the drafter as separate files

Source: `peasantsmith/DeepSeek-V4.1-Flash-1017-Maya-GGUF` README (fetched, 4.7 KB) and
the HF API file listing (`%TEMP%\maya-gguf-files.json`).

| File | Size | What it is |
|------|------|------------|
| `dspark/dspark.bin` + `.json` | 7.97 GB | Maya-S's drafter - DeepSeek's FP4 experts kept (`"experts": "keep"`, MXFP4), dense parts Q8_0 |
| `dspark/dspark-xs2.bin` + `.json` | 4.25 GB | Maya-XS's drafter - its own 2-bit experts |
| `dspark/dspark-xs.bin` + `.json` | 3.40 GB | Present in the repo, not tabled in the README (intermediate variant) |

- The GGUF shards hold model + Engram tables only (Maya-S: shards 1-4 model, 5-6 Engram;
  Maya-XS: 1-3 model, 4-5 Engram). The drafter is **not in the GGUF**.
- `dspark.json` is a tensor manifest: `{"from": "dspark.bin", "experts": "keep",
  "dense": "Q8_0", "tensors": [["mtp.0.attn.attn_sink", "F32", 0, 256, [64]], ...]}` -
  name, dtype, offset, byte length, shape for every `mtp.*` tensor in the .bin.
- Pack memory math (README): Maya-S 178.2 GB in-mem + 8.0 GB drafter + 161.3 GB Engram
  from SSD (347.5 GB download); Maya-XS 115.3 GB + 4.3 GB drafter (280.9 GB download).
  On the lab box's 112 GB usable RAM, Maya-XS + drafter is the tight-but-fits option;
  Maya-S needs the Engram-on-SSD path and the drafter's 8 GB in the RAM budget.

## 3. How the ds4 engine loads and runs the drafter

Source: `mw00/project-maya` `src/ds4/ds4_main.cpp` (60 dspark lines), `ds4_model.hpp`,
`ds4_packinfo.cpp` (28 dspark lines), all fetched raw.

- **Loader** (`ds4_packinfo.cpp`): reads drafter config from pack metadata
  (`dspark_block_size`, `dspark_noise_token_id`, `dspark_markov_rank`,
  `dspark_n_routed_experts`, `dspark_num_experts_per_tok`, `dspark_target_layer_ids`),
  then counts `mtp.<i>` blocks in the pack's tensor table (probing
  `mtp.<i>.attn.wq_a.weight`), cross-checks expert counts, and warns on any mismatch
  (missing config beside present tensors, block size 1 or >16, target layer not a trunk
  layer, Markov rank vs embed shape). `has_drafter()` is false "for a pack without them
  or --dspark none".
- **CLI**: `--dspark on|off|none` (none = not even loaded; off = loaded, resting),
  `--dspark-conf F` (confidence floor, default 0.5, per-request overridable via
  `dspark_conf`/`spec_cum` keys). `--spec-eval` and `--sampler-test` require a drafter.
- **Policy knobs**: `MAYA_DS4_DSPARK_CUM` (cumulative-confidence cut),
  `DS4_DRAFT_COST=1` (size the draft window by measured per-row cost instead of the
  confidence product - "the cost-aware window of strata/spec/draft_policy.hpp"),
  `DS4_DSPARK_SAMPLE=1` (draw drafts from the drafter's distribution). A separate
  **prompt lookup / suffix drafter** (n-gram-style) runs beside or alone of DSpark.
- **Placement**: `DS4_DRAFT_GPU` (device ID, from the startup printout, not TP-group
  position) places the drafter on one GPU; `draft_experts`/`draft_cpu` move drafter
  experts to the CPU lane.
- **Stats**: `dspark: N rounds, M drafts offered, K accepted (X.XX tokens a round)`
  plus per-position acceptance; Prometheus gauges `maya:engine_draft_rounds`,
  `maya:engine_draft_ms`, `maya:engine_verify_ms`; `docs/ds4-draft-timing.md` documents
  the STAT lines.
- **Sizing note for the port**: the drafter's blocks are ordinary attn + MoE layers
  (128 routed MXFP4 experts per block, Q8_0 dense) - the same kernel families (grouped
  XMX GEMM, attention) the ds4 port needs for the trunk, plus the rank-256 Markov head.
  No exotic drafter-only op set.

## 4. Is the GLM port's draft machinery reusable for A'

Source: lab GLM SYCL port README (`.../b70-lab/glm-5.3/sycl-port/README.md`).

- The live GLM-5.3-Flash port runs an **MTP draft stage in 4-card split decode**:
  cards 0,1 draft position q+3 while cards 2,3 verify q+2; draft cost 2.23 ms after
  fixups35; decode 45.5-45.8 tok/s (768-token runs). That is production proof that a
  draft stage composes with split-mode SYCL decode on this exact hardware.
- But it is the `maya` engine (GLM) with GLM's 1-layer MTP block drafting one position
  ahead. DSpark drafts blocks of 5 from three stacked blocks with a Markov head - a
  different draft shape in a different engine. What transfers:
  - the pipeline structure (draft on head cards while tail verifies, host sync points),
  - the SYCL-side lessons from 36 fix rounds (graph capture limits, split-mode rules,
    barrier placement - e.g. the KDA-graphs regression and the early-tail no-gain),
  - the measured draft/verify timing methodology.
  What must be built: the ds4 engine's DSpark `draft()` path on SYCL (its kernels are
  the standard families listed in section 3, and the GLM port's grouped-XMX reuse shows
  the port can lean on the llama.cpp fork's kernels for GEMM).

## 5. Impact on the engine decision

- **A' gating risk (was: "does a 1017 pack carry a usable drafter?") - cleared.**
  Official packs carry it (4.3-8.0 GB, separate files, manifest-verified), the engine
  treats it as first-class, and a drafter is proven live on 4 Arc cards in the sibling
  port. The remaining drafter work in A' is the ds4 DSpark path on SYCL, which is
  bounded kernel work, not an open question.
- **B (yardstick) asymmetry noted**: the on-disk llama.cpp pack has zero `mtp.*`, so
  the yardstick baseline decodes without a drafter. If A' ships drafting, the decode
  comparison favors A' structurally; the fair yardstick comparison for the *non-draft*
  path is still the warm llama-bench numbers (pp32 0.65 / tg8 3.92).
- **Pack choice for A' (open question b, refined)**: Maya-XS (115.3 GB in-mem +
  4.25 GB drafter + 161.3 GB Engram on SSD) fits the 112 GB RAM budget with little
  slack; Maya-S (178.2 GB) needs the full SSD-tiering path plus 8 GB drafter headroom.
  The on-disk GSQ-RCO IQ2_XXS 128.75 GiB + IQ4_NL Engram pack is a llama.cpp-format
  pack - usable for B, not directly for A'.

## Sources

- `huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash-1017` - `model.safetensors.index.json`,
  `config.json` (fetched 2026-11-16, cached in `%TEMP%`).
- `huggingface.co/peasantsmith/DeepSeek-V4.1-Flash-1017-Maya-GGUF` - README,
  `dspark/*.json` manifests, HF API file listing (fetched 2026-11-16).
- `github.com/mw00/project-maya` - `src/ds4/ds4_main.cpp`, `src/ds4/ds4_model.hpp`,
  `src/ds4/ds4_packinfo.cpp` (raw, main branch, fetched 2026-11-16).
- Lab: `.../b70-lab/glm-5.3/sycl-port/README.md` (MTP pipeline, fixups35),
  `.../DEEPSEEK-1017-PLACEMENT-SWEEP-2026-11-12.md` (line 316, zero `mtp.*` in the
  lab pack).
