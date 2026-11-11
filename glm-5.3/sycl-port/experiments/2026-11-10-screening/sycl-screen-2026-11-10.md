# GLM-5.3 Maya SYCL sub-batch screen — 2026-11-10

## Decision

Promising but not ready for production. Do not apply the candidate: the machine has tight card headroom, the numerical comparison found one changed top token, and no acceptance budget has been declared. This is a configuration experiment, not a new kernel implementation.

## Setup

Zeus, four B70s, isolated server at 127.0.0.1:9073. Runtime <work>\rt-live\generate.exe SHA-256 497f1d4238a724eafbf056af33910e4e0d94e6b7571a33ae61187512b0ca7198. Maya source tree reports upstream 5d20b0e8; correspondence between generated source and binary has not been fully verified. Both arms used the live 128k config, chunk 768, layer split 13,24,35, resident-skip on, CPU lane off, 400 MB reserve, same weights, runtime and corpus. Baseline used default mixer sub-batches of 512; candidate set STRATA_GLM_PREFILL_SUB=768. Runtime allocation log shows candidate borrowed 745 MB vs 657 MB for prompt scratch on CUDA3. GPU processes were run one at a time; swap was empty during measurements.

## Timing

Fresh prompt first-token times, 64 output tokens, same corpus and token counts:

| Arm | 8,227 prompt tokens | 33,091 prompt tokens |
| --- | --- | --- |
| Baseline A1 | 8.079 s, 3 samples | Not measured |
| Candidate B1 | 7.773 s, 3 samples | Not measured |
| Candidate B2 | 7.716 s, 3 samples | 28.751 s, 3 samples |
| Baseline A2 | 8.165 s, 3 samples | 29.769 s, 3 samples |

At 8k the pooled candidate mean 7.7445 s vs baseline mean 8.122 s is 0.378 s or 4.65% lower. At 33k the candidate mean is 1.018 s or 3.42% lower; this comparison has only a closing baseline, so is less robust. At 8k the engine's warm fresh prefill logs show ~7.37–7.39 s candidate and ~7.65–7.77 s baseline. Exact tokenized sizes are shown; TTFT includes server preparation. Each input varied early in its prefix and logs verified full prompt processing. A batch named sub768-repeat8k was a prefix-cache hit (~0.6 s TTFT) and must be excluded from fresh-prefill results. There was no 100k/128k test.

Varied short-prompt sbench, temperature 0, thinking disabled: A1 48.3 tok/s and B 48.3 tok/s, each 28 measured replies (5 rounds, first discarded). Output counts differ for at least one prompt, so the means are descriptive rather than matched-token kernel timings. Long-prompt continuation answers also differed despite the same prompts.

## Correctness and memory

Four squal answers were byte-identical across A1, B and A2 and factually correct, though JSON and math output formatting did not fully follow output-only instructions. This is not a complete quality test.

The CLI teacher-forced test used the same 8,192-token file (SHA-256 83fdbbbd0bdd60cae5f985d69b23defe180a696aac13dc15f87c086b1fe80fab), 8,128 tokens in prefill and the last 64 as forced decode tokens, speculation disabled in both arms. Full-vocabulary comparison over 64 rows: mean KL 0.01107, max KL 0.08258, top-1 agreement 63/64, maximum absolute logit difference 3.7089. One corpus is not a quality guarantee, and no agreed threshold exists. No inference that the change is acceptable follows from these values.

Startup reported complete expert pools; tested runs logged no CPU or disk expert fetches, and candidate engine logs reported 0.6 GB free on the tightest card after 33k prefill. Windows adapter counters showed ~31.2 GiB dedicated on its busiest card and ~3.5 GiB shared per adapter during the candidate run. Shared allocation can include pinned host buffers; these counters alone neither prove nor rule out WDDM spill. Further memory and image testing is required.

## Provenance and next steps

Raw logs, configurations, timing JSONL, 64-row logits, runner and manifest: Zeus <work>\experiments\codex-20261110. The local original baseline JSON SHA-256 4cb0cc97338c67d3dbdc3f26c17b4beb9a2a0987f11cbaa041e5e18e5461b812; candidate db8b63ed84e600c2c1bc701cbbaf9d9d35ef7dacc661ae258b56b70a46a6d9cf. sbench.py SHA-256 bd39d23491242d2e60fa1a22a84dd11f5d086441fbdea199e3ffaafe8d1c4699; depth_bench.py final SHA-256 71f0869c5f659facbf099ae221ce08c5aeed0b756ffee1686f8b7ceb3b54d5f5. Baseline and first candidate were measured with the same script before the offset argument was added; it only changes the fresh-prefix index.

Before promotion: establish a quality budget and test a broader fixed corpus, long-context retrieval/continuation/tool use, image paths and memory residency, and the required 30-minute mixed soak. Run 100k/128k validation and measure prompt-edit/retry behavior. For actual kernel work, instrument the two per-head projections separately with low-overhead timing and decide whether their measured wall-time fraction supports the L1 gate. Inspect and validate L2 attention variants with operator comparisons before adopting them. Preserve the current runtime and config.
