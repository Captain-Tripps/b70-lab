# Inkling 2 Mini on one Arc Pro B70: a Windows port of steveseguin's inkling2 engine, plus matrix-engine expert kernels

**Short version:** Steve's `inkling2` engine (from `steveseguin/b70-optimization-lab`, `experiments/own-xpu-runtime/inkling2`) ported to Windows on one Arc Pro B70, given a C API so an existing Python chat server could run on it, plus speculative sampling with the drafter in that server. **Since 2026-11-26 the live build is upstream `f7cd9b47` with Steve's exact matrix-engine (XMX) experts,** which replaced our own XMX v3 kernels after an [A/B](#steves-exact-experts-vs-xmx-v3-2026-11-26-now-live). Served on 26-40k-token requests, the new build read prompts 2.7% faster and wrote 1.6% faster than v3 and used 0.7 GiB less card memory.

All the engine work is Steve's. Our part is the Windows port, the C API, the server-side speculative sampling and the earlier XMX v3 kernels. The sections from [Upstream commits](#upstream-commits) to [Quality checks](#quality-checks) describe the 2026-11-25 build.

## Steve's exact experts vs XMX v3 (2026-11-26, now live)

One B70, same card for every run, same model and drafter files.

| Arm | Engine | `INK_XMX` |
|---|---|---|
| A | 2026-11-25 tree (`e27bcf89` base) | 0 |
| B | 2026-11-25 tree, our XMX v3 (live until this test) | 1 |
| C | `f7cd9b47`, Windows port | 0 |
| D | `f7cd9b47`, Windows port, Steve's exact experts | 1 |

**Correctness** (3,033 and 29,034-token prompts, 200 greedy tokens, `ink_run`):

- A and C: identical token ids, last-prompt-token logits and generated logits. The port and the upstream changes between the two trees kept the values with XMX off.
- C and D, each against itself: identical on a repeat run, at prompt step sizes 512 and 4096, and with the drafter.
- D against C: KL 3.1e-3 and 5.9e-3 on the last prompt token; first different token at 170 and 9. "Exact" means the same output at every step size, not the same bits as `INK_XMX=0`.
- B against A: KL 2.3e-2 and 1.5e-3. Two prompts don't show which XMX version is closer to XMX off.

**CLI speed** (`ink_run`, greedy, 200 tokens, median of 3 rounds, tok/s; the prompts are public engine notes and source):

| Prompt | Drafter | A read | B read | C read | D read | A write | B write | C write | D write |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 3,033 | off | 1092.9 | 1400.1 | 1091.6 | 1455.8 | 81.0 | 81.0 | 80.6 | 79.1 |
| 3,033 | on | 1091.6 | 1394.1 | 1091.0 | 1454.4 | 111.8 | 113.5 | 116.9 | 112.3 |
| 29,034 | off | 969.3 | 1206.1 | 967.4 | 1248.6 | 71.5 | 71.7 | 71.2 | 69.8 |
| 29,034 | on | 965.6 | 1200.8 | 964.7 | 1243.7 | 76.9 | 87.5 | 79.7 | 88.0 |
| 100,034 | off | 742.1 | 871.2 | 740.8 | 888.1 | 51.7 | 51.8 | 51.4 | 50.8 |
| 100,034 | on | 740.0 | 869.0 | 740.0 | 886.8 | 61.1 | 59.1 | 63.0 | 61.1 |

Spread across rounds was at most 3.3 tok/s on reading and 0.37 on writing. D reads 1.9-4.0% faster than B. D writes 1.8-2.6% slower without the drafter; with it, 1.1% slower at 3K, 0.6% faster at 29K, 3.3% faster at 100K (drafted speed depends on the text each arm writes). The 100K prompt was timed but not part of the correctness check.

**Served** (Python server + DLL, 262k, `--chunk 2048`, drafter, six long requests, same seed, 3 rounds):

| | B (v3) | D (exact) |
|---|---:|---:|
| Prompt read | 1,115.6 tok/s | 1,145.8 tok/s |
| Writing | 71.25 tok/s | 72.42 tok/s |
| Six requests, wall time | 225.6 s | 222.8 s |
| Tokens generated (different text) | 6,742 | 6,895 |
| Card memory with drafter | 28.11 GiB | 27.42 GiB |

D read all six prompts faster, wrote five replies faster and one slower (72.6 vs 83.9 tok/s). Output quality wasn't scored.

**262k at `--chunk 4096`:** B doesn't load (short 288 MiB). D loads at 30.10 GiB and answered one request.

**Decision:** our rule going in was to keep v3 if D wrote slower than it, beyond the spread, with the drafter on. The 3K case missed that by about 1%. We switched anyway on the served results.

**localmaxxing, verified** (`reasoning-v1` prompt, 512 output tokens, 3 timed runs, 2026-11-26): **79.4 tok/s writing** (79.3-79.5), time to first token 356 ms, prompt reading 820 tok/s, estimated from TTFT. This run had the **drafter off**, on a temporary server with the live DLL and settings, so it isn't the live writing speed. With the drafter on, against the live endpoint, the same benchmark measured 103.2 tok/s (99.7-120.8, dry run only, not submitted): the site's drafter check assumes a fixed number of guesses per round and ours varies up to 3, so that run doesn't verify. [Run page](https://www.localmaxxing.com/en/runs/cmwybkdd2000dp601258a50uv).

**Port changes for `f7cd9b47`:** `cache_file.hpp` and the serve-mode stdin loop in `ink_run.cpp` use new `wincompat.hpp` wrappers, and `wincompat.hpp` has to `#undef OUT` after `windows.h` (it collides with `Vision::OUT`). `device.hpp` and `gguf.hpp` merged cleanly. Our `engine.hpp` hook and `moe_xmx*.hpp` are gone. Upstream has moved on past `f7cd9b47` since (including matrix-engine attention); none of that is tested here.

## Run conditions

- **Hardware:** one Intel Arc Pro B70 (32 GB), Windows 11, the only card used for every number here. Other cards in the box were idle or unloaded during the runs, except where noted.
- **Model:** Inkling 2 Mini UD-Q4_K_XL (Q8_0, NVFP4, BF16 and F32 tensors), converted to the layout `inkling2` reads. Drafter: Unsloth's `dspark` Q8_0 "Old_Support" file (383 MB).
- **Compiler:** Intel oneAPI DPC++, JIT device code, the same card target as Steve's build.
- **Builds referred to below:**
  - `bench_xmx`: a standalone kernel benchmark (our `tools/bench_xmx.cpp`) that times only the expert kernels on real layer weights.
  - `ink_run` CLI: Steve's command-line runner, greedy, built from our tree.
  - served `steve6`: our C API DLL with XMX v3, behind the Python server. Live until 2026-11-26.
  - Earlier served DLLs: `steve4` (first DLL with ring snapshots) and `steve5` (pulled the newer upstream commits).
- **Run counts:** every number is tagged with how many runs it comes from. Most are single runs. Where I don't have a run count on record, I say so rather than guess.

## Upstream commits

**Base:** `1d3a7d04` (2026-11-25 03:05 UTC), "loop-control outputs in their own 64-column kernel".

**Pulled in afterwards,** as one tree update through `e27bcf89`:

| Commit | What it adds |
|---|---|
| `b3b34c20` | Loop mix scores |
| `5b2c2eb6` | Prompt step size by context: 4096 up to 64K, 2048 up to 128K |
| `6a816734` | Kernel preload at model load |
| `3ade634e` | Profiler |
| `720a5530` | Prompt lookup beside the drafter |
| `e27bcf89` | Learned lookup rule |

**Not pulled** (`4ac839fe` onward): the drafter head over a built-in list, 530K context, his serving/LAN server, sampling, 480K recall, pictures, several conversations, and the thinking budget.

The most important ones that build didn't have were Steve's own matrix-engine experts: `3fceff9b` (NVFP4 experts on the matrix engines with exact products), `3cfebbc2` (small steps) and `f7cd9b47` (2026-11-26 00:36 UTC, exact matrix-engine experts on by default, +15-34% prompts by Steve's numbers). Steve's version is exact and ours isn't. Anyone starting fresh should take it. It's [live here since 2026-11-26](#steves-exact-experts-vs-xmx-v3-2026-11-26-now-live).

## What we changed, and why

The diff against `e27bcf89`: `attn_flash`, `fused`, `ops` and `ink_run` are unchanged. `device.hpp` and `gguf.hpp` only change for Windows file I/O. `engine.hpp` gets the XMX hook. Everything else is new files.

| Change | Why |
|---|---|
| `wincompat.hpp`: `ink_open` / `ink_pread` / `ink_lseek_end` / `ink_close` / `ink_aligned_alloc` / `ink_aligned_free`, used in `device.hpp` and `gguf.hpp`; `.bat` build scripts for the exe and DLL | The engine uses POSIX file calls and `aligned_alloc`. These are the only changes needed to build and run on Windows. |
| Model converter (Python) | Our GGUF uses the newer tensor layout. The converter rewrites it to the layout `inkling2` reads. Checked bit-exact against Unsloth's own Old_Support file (see quality checks). |
| Older drafter file | Unsloth's newer drafter file is a different format from the one the engine reads. |
| `tools/ink_capi.cpp`: a C API DLL matching the interface of the engine we used before (ArcAngel) | The engine is a greedy command-line tool. Matching an existing C API meant an existing Python server (chat template, sampling, thinking budget, prompt cache and checkpoints) ran on it unchanged. |
| Ring snapshots through a card-side staging buffer, window only (`steve4` onward) | Conversation switching and prompt checkpoints need the state saved and restored. Pinned host memory (`malloc_host`) fails on this setup, so snapshots go through a device buffer instead. |
| Server: speculative sampling with the drafter (`--draft`) | Steve's drafter is measured greedy. For sampled output, the server samples each checked row and keeps the drafter's guess only while the sample equals the guess. That's exact: the output distribution is the plain sampler's. |
| Server: faster sampler | A threshold sampler, 1.15 ms to 0.45 ms per token. |
| Server: incremental detokenize | The old parser re-decoded the whole reply each step, so its cost grew with length. Output text checked equal. |
| `engine.hpp` + `moe_xmx.hpp` / `moe_xmx2.hpp` / `moe_xmx3.hpp`: XMX expert kernels behind `INK_XMX=1` (NVFP4 experts only) | A profile at a 29k-token prompt put 53% of prompt-read time in the expert layers, which weren't using the matrix engines. Inputs go to half precision, as llama.cpp does it, so results aren't bit-identical. |
| `tools/bench_xmx.cpp` | An engine rebuild took ~13 minutes per kernel change. The benchmark builds the kernels alone and compares speed and error against Steve's kernels. |

## XMX results

`bench_xmx` on the one B70, real layer weights, 4,096-token chunk, 32,768 slots, 2,114 tiles, 20 timed iterations per measurement. One bench run per variant. Errors are against Steve's kernels.

| Version | gate_up | down | Notes |
|---|---:|---:|---|
| Steve's kernels | 28.0 ms | 14.5 ms | Reference |
| v1 (TB4 NSG8) | 139.2 ms (0.20x) | 56.6 ms (0.26x) | Correct, but 2.6x slower than Steve's in the engine |
| v2 (TB4 NSG8) | 33.8 ms (0.83x) | 11.4 ms (1.27x) | gate_up error 1.91 max, 1.15e-2 RMS |
| v2, TB8 variants | 32.3-32.5 ms | 13.5-14.6 ms | |
| v3, first version | 16.8 ms (1.66x) | 9.4 ms (1.54x) | |
| v3, final (gate_up KC32 TB4 NSG16, down KC64) | 15.3 ms (1.83x) | 9.7 ms (1.49x) | This is what was in `steve6` |

**What changed in each version:**
- **v1:** one work group looped over several experts, decoded weights byte by byte, and staged inputs in shared memory.
- **v2:** each block holds up to TB tiles of a single expert, weights are decoded 32 values at a time, and inputs are read straight from global memory with no staging.
- **v3:** each sub-group decodes its own weights, so there are no work-group barriers.

**What failed:**
- **Shared-memory input staging** made it slower. v2 dropped it, and that was part of v2's gain.
- **Splitting inputs into hi/lo halves** for more precision ("XS") changed nothing, in error or speed.
- **The gate_up error outliers.** About 0.08% of gate_up values disagreed in sign with Steve's kernels on random inputs. Recomputing the worst ones in fp64 on the CPU showed it isn't a bug: random inputs create huge cancellations, and the matrix engine's internal sums are slightly less precise than plain fp32 math. Real activations don't hit this, as the KL check below shows.

**In the engine** (`ink_run` CLI, 29k-token prompt, greedy, 1 run per arm):

| | Steve's kernels | XMX v3 |
|---|---:|---:|
| Prompt read | 29.7 s (974 tok/s) | 24.0 s (1,206 tok/s) |
| Decode | 71.5 tok/s | 71.5 tok/s |

**Served** (Python server + DLL, same seed for both arms):
- 6 beat prompts, 1 pass per arm: 46.1 s to 40.1 s per prompt.
- 39 prompts, 1 pass per arm: prompt reading 853 to 1,181 tok/s, writing 71 to 83 tok/s. The writing difference is probably from different outputs, not the kernels (decode doesn't use them). Rewrite-rate differences between the arms were within the noise of our scorer.

## Speed progression, served

The one B70, the served Python server, sampled output, 26-40k-token prompts. Each row comes from the served test runs of that build. I don't have exact run counts for the first three rows, and the last two are from one pass each (~ marks a rounded figure from that pass).

| Setup | Writing | Prompt reading |
|---|---:|---:|
| Previous engine (ArcAngel), for reference | 58.4 tok/s | 1,042 tok/s |
| Steve's engine, plain (DLL) | 63.3 | 816 |
| + speculative sampling and server fixes | 71.3 | 863 |
| + newer upstream (`steve5`) | ~71 | ~957 |
| + XMX v3 (`steve6`) | ~74 | ~1,189 |

**CLI, greedy** (`ink_run`, 29k-token prompt, 1 run each): 71.7 tok/s plain, 77.5 tok/s with the drafter (+8%), prompt 922 tok/s. The drafter gains less on prose than on code: Steve reports about +38% on code.

**localmaxxing standard benchmark** (`reasoning-v1` prompt, 512 output tokens, against the live endpoint, 2 runs): 98.9 and 100.8 tok/s writing, time to first token 347 and 348 ms, prompt reading ~850 tok/s, estimated from TTFT. Submitted and approved, listed as not verified, because our server doesn't report draft-token counts.

## Quality checks

| Check | Build | Runs | Result |
|---|---|---|---|
| Converted model vs Unsloth's Old_Support file | `ink_run` CLI | 1 | Logit difference 0.0, same token ids |
| Speculative vs plain, greedy | `ink_run` CLI | 1 per arm | Identical tokens |
| Speculative sampling, fixed seed, 3 drafter settings | served DLL | 1 per setting | Same text word for word |
| Prompt cache and conversation switch vs cold | served DLL | 1 each | Identical text |
| XMX v3 vs Steve's kernels, first output token | `ink_run` CLI, 29k prompt | 1 | KL 7.07e-3; same top token (p 0.81 vs 0.77); greedy text matches for 40 tokens, then takes a different, equally fluent path |
| Recall: 3 facts hidden in a long prompt | served `steve6` | 1 per size | 3/3 at 113k (806 tok/s read, 67 tok/s write); 3/3 at 216k (580 read, 51 write) |
| 262k vs 131k context, same 45k prompt | served `steve6` | 1 per size | Identical output; 42.3 s vs 41.6 s |
| Runaway replies: 3 prompts x 3 seeds | served, XMX on vs off | 9 per arm | On: 3/9 ran away, all one seed, reproducible. Off: 1/9. Seed luck, not the kernels |
| Audit task: catching planted errors, 36 of 42 cases, vs Qwen 27B | served DLL (pre-`steve6`) | 1 | See table below |
| Structured-plan replay: 11 recorded prompts, 42-70k tokens | served `steve6`, thinking on | 1 per prompt | See below |
| Blind prose read vs Gemma 26B-A4B, 5 matched passages | served DLL | 1 reader | Gemma preferred 4-1 |

**Audit task** (same prompt, cases and scoring for both models; 1 pass):

| Arm | Planted errors caught | Unplanted passages flagged | Median time |
|---|---:|---:|---:|
| Inkling, thinking off | 21/22 | 11/14 | 13.8 s |
| Qwen 27B, thinking off | 21/22 | 12/14 | 10.6 s |
| Inkling, 1,024-token thinking cap | 19/22 | 6/14 | 19.1 s |
| Qwen 27B, 1,024-token thinking cap | 20/22 | 12/14 | 36.4 s |

With thinking off they tie, and each missed the same single case. Qwen's numbers are from two cards, Inkling's from one.

**Structured-plan replay:** Inkling replayed 11 recorded long prompts that ask for a structured plan, at 1.5-2.5 minutes each, with no runaways. All the per-item schema checks passed. All 11 left out one required heading line, and plans for the shortest section came out too thin (4-5 items where 7 were required). A 4k thinking budget gave the same output as 1k: Inkling stops thinking on its own after a few hundred words. So it doesn't follow that format as reliably as the model it was compared with, without prompt changes.

**Verdict:**
- **The port and the server are correct.** Conversion is bit-exact, greedy speculative output is identical to plain, cache restores are identical, and long-context recall works to 216k.
- **XMX v3 is accurate enough for prose, but not exact.** The KL is small and the top token matches. In the one sampled test, runaways tracked the seed, not the kernels. Where bit-exact output matters, use Steve's exact XMX experts (`f7cd9b47`) instead.
- **As a model, it's a strong one-card option for speed, auditing and long context.** On prose it ranked below Gemma 26B-A4B in one small blind read.

## Context limits

The one B70, `steve6` served, with the drafter loaded, 1 load each:

| Context | Prompt step (`--chunk`) | Fits? | Memory |
|---|---:|---|---:|
| 262,144 | 2048 | Yes | 28.1 GiB |
| 262,144 | 4096 | No, out of memory by 288 MiB | - |
| 131,072 | 4096 | Yes | 27.5 GiB |

- **Running at 262k costs nothing at shorter prompts:** 42.3 s vs 41.6 s on the same 45k prompt (1 run each).
- **An earlier 40,960 setup silently cut off the longest prompts.** Prompts around 40.6-40.8k left no room after thinking, and the reply came back empty with `finish_reason: length`. Easy to miss in aggregate scores.

## Known bugs and limits

- **XMX v3 (retired) wasn't bit-exact** against Steve's kernels (above).
- **Checkpoints silently turn off** when the checkpoint interval isn't a multiple of the prompt step. No error is shown.
- **An exact repeat of a prompt after a conversation switch re-reads it cold.** Snapshots don't store logits. The previous engine does the same.
- **Pinned host memory (`malloc_host`) fails** on this setup, so snapshots go through a device buffer.
- **No `draft_n` / `draft_n_accepted` in server responses,** so benchmark sites can't verify the speculative-decoding speeds.
- **A test-only minimum-length rule broke output.** It worked by masking EOS. When the model wanted to stop, it emitted space-free junk and never got past the floor. It needs a cap or a repetition guard, and it isn't used in the live setup.
- **Only NVFP4 experts take the XMX path.** Everything else runs Steve's kernels.

## What's live now

- One B70, behind a model-swap proxy that unloads it when the larger multi-card models load.
- A frozen runtime: the Python server with speculative sampling, plus a DLL built from `f7cd9b47` with the Windows port.
- Settings: `n_ctx` 262144, `--chunk 2048`, `INK_XMX=1` (Steve's exact experts), checkpoint interval 4096, `spec-k 3` with the Old_Support drafter. Card memory 27.42 GiB.
- Used as a one-card backup and a fast long-context model. Not the main prose writer.

## Next steps

- Test upstream's newer commits, starting with matrix-engine attention.
- Report draft-token counts from the server.
- The recall, audit and replay checks above ran on the 2026-11-25 build; they haven't been repeated on the new one.
