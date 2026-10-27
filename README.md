# b70-lab

Notes, patches, reproducers and benchmark numbers from running large local LLMs on **4x Intel Arc Pro B70**
under Windows 11. I'm sharing them so other Arc users can reuse what was debugged here, and so the numbers
(including the ideas that did not work) are in one place.

Highlights thread on X (2026-10-17): [Strata on 2x Arc Pro B70 under Windows](https://x.com/realjstaples/status/2111636473334157775).

This is a personal lab notebook, not a product. Everything was measured on one machine; your results on other
Arc cards, other drivers or Linux may differ.

## The test machine

| Item | Value |
|---|---|
| GPUs | 4x Intel Arc Pro B70, 32 GB each (Xe2, BMG-G31) |
| CPU / board | AMD EPYC 7402P (Zen 2, 24 cores, no AVX-512), ASRock Rack ROMED8-2T |
| System RAM | 64 GB DDR4 RDIMM until 2026-10-13, 112 GB since (7 x 16 GB; one slot fails its BIOS memory test) |
| OS | Windows 11 Pro (build 26200) |
| Compiler / runtime | Intel oneAPI 2026.0 (DPC++ compiler, oneMKL), Level Zero UR "v2" adapter |
| GPU driver | 32.0.101.8976 since 2026-10-11; 32.0.101.8805 before that |
| Builds | llama.cpp: AOT for the `bmg_g21` target (runs on the B70), `GGML_NATIVE=OFF` with AVX/AVX2/FMA/F16C (see [hardware-and-windows-notes.md](hardware-and-windows-notes.md)). Strata: JIT build (its AOT target would be `bmg-g31`) |

Before 2026-09-30 the box had 2 B70s and a Ryzen CPU. Numbers from that period are marked as such.

**Start with [STATUS.md](STATUS.md)**: one table of every idea tried, with its gain or loss and whether it is
live, staged, rejected or an open bug. [CHANGELOG.md](CHANGELOG.md) has the dated history.

## DeepSeek V4.1 action plan

[Native Windows Strata V4.1 port plan](deepseek-v4/strata-v41/PLAN.md) (2026-10-26): reuse the existing Windows/JIT
foundation, qualify four-card transfers, port the separate DeepSeek engine, then validate and profile it.
Status: **planned, not implemented or benchmarked**. Start with the
[OpenClaw/hosted DeepSeek handoff](deepseek-v4/strata-v41/OPENCLAW-START.md): qualify the native Windows runner,
then reconcile current usable RAM with historical notes. Existing Qwen and DeepSeek V4 results remain unchanged.

## What is here

| Folder | What | Status |
|---|---|---|
| [llama.cpp-sycl/](llama.cpp-sycl/) | My changes to llama.cpp's SYCL backend: what each does, measured gains, upstream PR status | 2 merged upstream ([ggml-org/llama.cpp#29604](https://github.com/ggml-org/llama.cpp/pull/29604), [ggml-org/llama.cpp#29809](https://github.com/ggml-org/llama.cpp/pull/29809)), 1 open ([ggml-org/llama.cpp#30358](https://github.com/ggml-org/llama.cpp/pull/30358)); the rest live in a local fork or staged |
| [flash-next/](flash-next/) | Qwen3.8-Flash-Next (180B MoE, 512 experts, 10 per token) tuning: 49 -> ~61 tok/s decode in llama.cpp | live |
| [deepseek-v4/](deepseek-v4/) | DeepSeek V4 Flash: IQ2_XS/IQ3_XXS MoE kernel, DSpark drafting, sparse attention at depth | live |
| [glm-5.3/](glm-5.3/) | GLM-5.3-Flash (321B MoE) brought into the fork: 16.5 -> 24-25 tok/s | live |
| [gpt-oss/](gpt-oss/) | gpt-oss-120b: MXFP4 reorder, 3-card layer split, cross-card pipeline | live; MXFP4 work merged upstream |
| [strata-windows-port/](strata-windows-port/) | Native Windows port of the Strata engine; Level Zero has no peer access between B70s on Windows | current best for Flash-Next: 2 cards, IQ3_S, int8 KV, JIT build, `--ple-io mmap`: ~99 tok/s decode, ~1,420 tok/s prompt read (112k prompt: 1,433 tok/s), 2-hour soak clean, vision working. An AOT miscompile caused the earlier wrong answers |
| [reproducers/](reproducers/) | Standalone programs: Level Zero multi-thread submission deadlock, Windows peer-access probe | deadlock still present on driver 8976; reported to Intel ([forum](https://community.intel.com/t/144119), [intel/llvm#23530](https://github.com/intel/llvm/issues/23530)) |
| [bench/](bench/) | Benchmark scripts and how to compare fairly | |
| [rejected-ideas/](rejected-ideas/) | Things that did not help, with numbers | |
| [hardware-and-windows-notes.md](hardware-and-windows-notes.md) | Windows/driver gotchas: idle VRAM eviction, WDDM spill, build flags, downloads | |

## How to read the numbers

- **Decode** = generated tokens per second for one request, from llama-server's own `timings` or from streamed
  token times (see [bench/](bench/)). **Prompt read** = prompt tokens per second.
- Every table says which model file, runtime and harness it was measured with. **Compare numbers only within one
  table.** Different harnesses give different absolute numbers for the same server (for Flash-Next, one harness
  reads ~45 tok/s and another ~61 on the same build), because prompt length, output length and how much the
  draft model gets accepted all change the result.
- Runtimes are named after the fork build they came from: `rNN` (main fork, e.g. `r62`), `gNN` (GLM branch),
  `b70fu` etc. (older builds on upstream b11190). [llama.cpp-sycl/README.md](llama.cpp-sycl/README.md) lists what each contains.
- Speculative decoding numbers depend on the text: copy-heavy output (edits, reformatting) accepts far more
  drafts than fresh prose. Where it matters the tables give both.
- Correctness was checked with `test-backend-ops` against the CPU backend, perplexity / KL divergence, and
  fixed-answer prompts. A speed number without a correctness check is not worth much: the miscompiled int8-KV Strata
  build in [strata-windows-port/](strata-windows-port/) ran at 96 tok/s and produced garbage.

## Adding a new result

This is a living repo. Every new result, good or bad, gets:

1. A row in [STATUS.md](STATUS.md): item, model, gain or loss **with numbers** (before -> after), status, date, link.
2. The details in the topic folder: model file and quant, runtime (fork build or upstream commit), driver, cards
   and split, context, harness and sample count, and the correctness check used (op tests, perplexity / KLD,
   fixed-answer prompts).
3. A dated line in [CHANGELOG.md](CHANGELOG.md).

Failures go in too, in [rejected-ideas/](rejected-ideas/) with their numbers. Nothing here is written for posting to
llama.cpp.

## Status words

- **live**: what the test machine's servers run every day.
- **staged**: built and measured, not switched on.
- **upstream**: the change (or an equivalent) is in upstream llama.cpp or in review there; see [llama.cpp-sycl/](llama.cpp-sycl/).
- **rejected**: measured and dropped; see [rejected-ideas/](rejected-ideas/).

## About AI assistance and llama.cpp

The code, measurements and these notes were prepared with AI assistance. Patches here are for people who want to
run or study them.

llama.cpp has its own rules for AI-assisted contributions. This repository is not a place to discuss llama.cpp
pull requests, and nothing here is meant to be copied into llama.cpp issues or pull requests.

## Credits

This builds on a lot of other people's work: the ggml / llama.cpp authors and the SYCL backend maintainers and
reviewers (arthw and others); MTP / DSpark speculative decoding in llama.cpp (am17an, PR #25784); the Q8_0 ESIMD /
wide-load work by cwriter (#29186) and iki007's SYCL fork; Unsloth's GGUF quants; Project Maya's GLM-5.3 quants;
the Strata engine (Niko1221 and contributors, with the B70 work from hotschmoe and SergiioB); ISTA-DASLab's
GSQ-RCO quant. Mistakes in this repo are ours, not theirs.

## License

Docs and scripts written for this repo: see [LICENSE](LICENSE). Patches and files derived from llama.cpp and Strata stay under
their MIT licenses; the original notices are in [LICENSES/](LICENSES/) and each patch file names its source.
No model weights or binaries are included.
