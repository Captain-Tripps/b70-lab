# Changelog

Dated entries, newest first. Results go into [STATUS.md](STATUS.md) and the topic folder; this file records what
changed and when.

## 2026-11-24
- **DeepSeek V4.1 Flash 1017 `ds4`: decode queues without profiling, live. CLI decode +4-10%, served about +6%.** `dpct` creates every queue with profiling on, and on the v2 adapter that costs ~1.3 us of GPU time per dependent kernel, ~1,440 of them a token. fx63 drops it on the two decode queues; `DS4_QPROF=1` restores the old queues. Tokens identical on every CLI pair, prompt reads unchanged. Corrects the 2026-11-18 note that launch cost was not a decode lever. [Decode launch cost](deepseek-v4/maya-ds4-sycl/#decode-launch-cost-2026-11-24-queues-without-profiling).
- **Also tried, not kept:** a fused decode sum (stale reads, then a hang), the MoE routing wait on the GPU (exact, no gain), re-recording and updating a graph every token (~7% at best), eventless launches (~3-4%, ~140 sites, not done).
- **Next move for `ds4` decode: replay it as fixed SYCL graphs,** the way the GLM and Flash-Next ports already do. A static 1,440-kernel graph replays at 0.55 us a kernel against ~6 us eager. Per-token values such as position and sequence numbers have to move into device memory first; a multi-day port. [Plan](deepseek-v4/maya-ds4-sycl/#next-move-replay-the-decode-as-fixed-graphs).

## 2026-11-23
- **DeepSeek V4.1 Flash 1017 `ds4`: TP 2 prompt-read gap investigated, shelved.** Served decode at ~119k context 54.3 tok/s (no long-context cliff). Prompt reads stay ~20-25% slower: the long-prompt skip leaves layers 0-18 on one TP pair, each layer-chunk sync costs ~3.4 ms, and the 5 + 4 expert split can't be made even. [Details](deepseek-v4/maya-ds4-sycl/#long-context-and-the-slower-prompt-read-investigated-shelved).
- **DeepSeek V4.1 Flash 1017 `ds4`: tensor parallel 2 on Windows, live. Served decode +30-48%, prompt reads ~25% slower.** Two groups of two cards with the uneven expert split, no peer-to-peer. The 11-19 attempt was slow (10.6 tok/s: ~80 host waits a token at 2.3 ms, mostly Windows sleeps) and hung. A spinning kernel turns out to see a host-USM write if it fences each turn, so the waits moved onto the device (`DS4_DEVWAIT=7`), plus three hang fixes: the drafter's Markov pick on one card, drafter blocks spread so no expert spills to the CPU lane, and a queue-lock deadlock with the oneMKL warm-up thread found from `cdb` stacks. Served code 57.4 -> 84.1 tok/s, 99k context 46.5 -> 61.0; answers checked. [TP 2 on Windows](deepseek-v4/maya-ds4-sycl/#tensor-parallel-2-on-windows-2026-11-23-device-side-waits).
- **Correction: the 2026-11-17 "a running kernel never sees a host-USM write" was too broad.** It holds for plain and atomic loads; a system-scope fence before each load makes the write and the data before it visible in ~0.3 ms. New reproducer: [flag-visibility](reproducers/#flag-visibility-can-a-running-kernel-see-a-host-usm-write).
- **Two measurement traps from the TP 2 work.** The CLI bench reads prompts in windows of 16, not the server's chunks of 1024: it showed a 2x prompt read and a 108k decode drop that served runs do not have. And a served `prompt_n` counts only the tokens read new after a prefix-cache hit. [Measurement notes](deepseek-v4/maya-ds4-sycl/#measurement-notes).
- **Flash-Next prompt read +6.5% / +7.7%, live: the paired GDN recurrence from Strata PR #6566.** Ported by hand into this tree's prefill layout as `patches/0006` (three opt-in switches, each keeping the old sum order). 32k read 2,260 -> 2,407 tok/s on IQ3_S and 2,245 -> 2,419 on the abliterated IQ3_S, tokens identical; all of it from `STRATA_B70_GDN_PAIR=1`, the other two are noise and stay off. The recipe now applies 0006 and the published config sets the switch; the patch was checked to apply on the published chain. [PR #6566 port](strata-windows-port/#paired-gdn-recurrence-from-strata-pr-6566-2026-11-23).
- **DeepSeek V4.1 Flash 1017 `ds4` decode rounds 5-7: the drafter is done, nothing went live.** Stock DSpark at the live floors matched or beat every alternative: a self-distilled refit drafter (D1, decoded from EXL3 and applied as a delta: flat), native MXFP4 drafter experts (mixed, +3.7 GB), lookup drafting (DSpark already drafts 9-13 tokens a round on a code edit), `DS4_DSPARK_MAX=3` and re-tuned floors (neutral). No DFlash2 drafter exists for V4.1. A drafted round is 4.5-5.5 ms of draft and ~36 ms of verify, each extra verified token ~8 ms (two-thirds routed experts), and draft and verify cannot overlap. [Rounds 5-7](deepseek-v4/maya-ds4-sycl/#decode-rounds-5-7-2026-11-22--23-drafter-and-switches).
- **`DS4_MARKOV_Q8=1` looked like +4% and was a loss when served.** On the bench args its smaller head let the last card fit all its experts in VRAM; at the served 128k / chunk 1024 that effect is gone and it is -3% to -44%. Bench at the served args. [Measurement notes](deepseek-v4/maya-ds4-sycl/#measurement-notes).
- **Expert row shapes (fx45), a one-sub-group router top-k (fx46) and the existing decode switches: all inside run-to-run spread or worse.** [Rounds 5-7](deepseek-v4/maya-ds4-sycl/#decode-rounds-5-7-2026-11-22--23-drafter-and-switches).

## 2026-11-20
- **DeepSeek V4.1 Flash 1017 `ds4` serving: four changes, all live.** The engine config's empty `"sampling": {}` made requests without a temperature run greedy and loop in thinking; it now sets temperature 1.0 / top_p 1.0 and a thinking budget of 8,192. Sampled drafts (`DS4_DSPARK_SAMPLE=1`, `DS4_DSPARK_QTEMP=0.7`, exact): +2.3% at temperature 1.0 over 48 requests. Prompt chunk 1024: +9.8% at 108k (873 -> 959 tok/s), needle 5 of 5. Conversation slots (`MAYA_DS4_SLOT_KEEP=1`): a follow-up after another conversation restores in 0.0 s instead of re-reading 26k (~30 s) or 86k (~100 s). [Serving 11-20](deepseek-v4/maya-ds4-sycl/#serving-changes-2026-11-20-sampling-drafts-chunk-1024-conversation-slots).
- **The 2026-11-19 "chunk 1024 changes the 120k output" was prefill noise, not a chunk bug.** One 31k prompt gave 5 different greedy openings in 9 fresh runs at any chunk; an information test found no leak inside a chunk. Token hashes past ~8k are not an A/B check, and on this low-bit model perplexity across kernel shapes is noise. [Serving 11-20](deepseek-v4/maya-ds4-sycl/#serving-changes-2026-11-20-sampling-drafts-chunk-1024-conversation-slots).
- **Checked and left alone:** drafter floors at temperature 1.0 (noise), the engine's prompt lookup (adds nothing), sampler cost (+0.12 ms a verify step), long-context decode (30.7 tok/s plain at 120k).

## 2026-11-21
- **Strata Windows port README is now a step-by-step recipe for the live Flash-Next setup.** Hardware, driver, toolchain versions, sources at pinned commits, the patch order, the JIT build with the ESIMD GEMM, model pack, the live engine config, serving, how the numbers are measured and what to expect, and gotchas. Checked against the live machine: the patch chain applied to a clean `1c360526` checkout matches the live build's sources except comments and one log line. [strata-windows-port](strata-windows-port/#how-to-run-it).
- **Fixes found while checking:** `slow-starts/0003` did not apply on top of `slow-starts/0002` (it was cut against upstream's `ep_mem.hpp`), now rebased. The live `batch_poll` copy-stream fix (2026-11-17) was missing from the repo, now `patches/0005`. The ESIMD kernel files the build needs are now in `esimd-prefill/esimd/` instead of only coming out of the GLM recipe. The published engine config is now the live one (adds `STRATA_WIN_TIMER_MS=0` and the vision section).

## 2026-11-19
- **DeepSeek's round-4 decode levers tried on GLM and Flash-Next: one small exact win, live.** On GLM the aligned Q6_K mat-vec on 16-lane sub-groups (`STRATA_GLM_MV_AL16=1`) gains +0.5-0.7% over two rounds, with the 768-token output identical; live since the same evening. 256 registers for the spilling expert gate/up kernel cost 3%, and dropping `use_root_sync` from every launch is noise. [GLM lessons](glm-5.3/sycl-port/experiments/2026-11-19-decode-lessons/).
- **Flash-Next decode on Strata has nothing to port from DeepSeek.** Its dense kernels already run on 16-lane sub-groups and one decode kernel spills (~1.3% of kernel time). VTune `gpu-offload` does not see kernels inside replayed SYCL graphs, so the spill table came from an eager run; the serve-mode stage profile puts cross-card waits at 0.8% of a window and hyper-connection reads at 22%. [Decode profile](strata-windows-port/decode-profile-2026-11-19/).
- **DeepSeek V4.1 Flash 1017 `ds4` decode round 4, all live: drafted 37.5 -> 43.7 tok/s, plain 31.7 -> 36.2.** Five exact steps, the 256-token output identical in every run: a lane-packed dense Q6_K layout for sub-group block loads (fx37); 256 registers per kernel where it spills, the prompt experts (fx38) and the one-query decode attention (fx43, 3,968 B a thread); IQ1_S expert tiles and a group cap (fx40, fx41); drafter cut CUM 0.4; dense Q6_K on 16-lane sub-groups (fx43, plain +3.3%). The v2 Level Zero adapter is back on with `UR_L0_V2_DISABLE_ZE_LAUNCH_KERNEL_WITH_ARGS=1` (no stalls, 60-minute idle soak passed). Prompt read 812 tok/s at 8k, 867 at 120k (target 600+). [Round 4](deepseek-v4/maya-ds4-sycl/#decode-round-4-2026-11-19-day).
- **`ds4` prompt chunk 1024: 120k 867 -> 955 tok/s, not live.** The 120k output differs from the 4th token; 256 and 512 agree. Correctness check pending. [Details](deepseek-v4/maya-ds4-sycl/#prompt-read-already-past-the-target).
- **Rejected in round 4:** the expert down kernel on 16-lane sub-groups (no gain), lean dense addressing (superseded), registers for the drafter's Q8_0 mat-vec, persistent dense kernels, `DS4_IQ_AHEAD=1` (-25%). Micro-bench gains overstated engine gains 5-10x on this engine. [Tried and rejected](deepseek-v4/maya-ds4-sycl/#tried-and-rejected).
- **Windows B70 probes: no peer-to-peer, no same-card kernel overlap.** A host-staged hop costs +12-34 us; two queues on one card gain at most 6%. Tensor parallel and shared/routed expert overlap are parked for this OS. [Details](deepseek-v4/maya-ds4-sycl/#probes-that-closed-two-doors).
- **Measurement trap:** a VTune capture of the whole process counts the model load; its ~110 GB of expert uploads looked like 21% of prompt GPU time. [Details](deepseek-v4/maya-ds4-sycl/#measurement-trap-a-profile-that-includes-the-model-load).
- **DeepSeek V4.1 Flash 1017 `ds4` verify-width kernels (fx35) are live: drafted decode +1.9% (36.8 -> 37.5).** Exact-width dense Q6_K templates for verify windows are now the default (`DS4_Q6T_MC=1`), and router windows of 2-8 rows take the one-launch-a-token path (`DS4_ROUTER_SMALL`). CLI drafted 36.80 -> 37.48 over 3 alternating runs, plain and 8k read unchanged, output and acceptance identical. A 4-rows-a-work-item variant was about 2x slower, so the Q6_K kernel looks issue bound and the next step is XMX int8. [Details](deepseek-v4/maya-ds4-sycl/#verify-width-kernels-fx34-fx35).
- **`ds4` tensor parallel 2 with the uneven expert split: loads, then hangs (parked).** The fallback to TP 1 comes from n_ff 2304 = 9 blocks of 256. `DS4_TP_GGUF_UNEVEN=1` splits them 5 / 4 and fits every expert in VRAM, but `--tp 2` runs threads mode, where the first cross-card flag is never raised and every layer's CPU-lane wait times out. [Details](deepseek-v4/maya-ds4-sycl/#tensor-parallel-2-with-the-uneven-split-2026-11-19).
- **`ds4` drafter settings re-checked: the live floors stay.** Cost-based draft cut -4%, CUM 0.05 -3 to -4%, other pairs within noise. [Details](deepseek-v4/maya-ds4-sycl/#drafter-settings-re-checked).

## 2026-11-18
- **`ds4` drafted rounds 16% cheaper, live: per-row tap copies (fx33) and `--reserve-mib 768`.** `dpct`'s pitched copy freed its temporary buffer in a `host_task` that stalled the queue three times a round, and 33 unused CPU-lane experts on the last card made its layers wait for the CPU every token. Round 60.1 -> 50.7 ms, idle 12.1 -> 6.2 ms, 120k read unchanged (811.6). [Details](deepseek-v4/maya-ds4-sycl/#drafted-rounds-two-stalls-found-and-fixed-fx33---reserve-mib-768).
- **Host launch cost is not the `ds4` decode limit.** ~7.5 us a launch however launched; inside a layer the host runs ahead of the cards. Immediate command lists off is 5.1 us but hung decode 3 of 4 runs. [Details](deepseek-v4/maya-ds4-sycl/#host-launch-cost-is-not-the-limit).
- **`ds4` prompt read 282 -> ~765 tok/s at 8k, live: hand-off copies on the copy engine (fx31).** A classified per-card timeline showed the cards busy in a kernel-store copy of each chunk's hand-off, ~1.0 s a chunk; a queue `memcpy` takes ~10 ms. 120k 305 -> 808, 2k 195 -> 470, output identical. [Details](deepseek-v4/maya-ds4-sycl/#hand-off-copies-on-the-copy-engine-fx31).
- **`ds4` decode switches live: `DS4_HC_STREAM=0` + `DS4_HC_FUSE=2`.** Plain decode 28.5 -> 32.1, drafted 36.2 -> 37.6, decode after 8k 23.2 -> 27.3. The engine also got a llama-swap entry (owner's OK), behind Maya's OpenAI-compatible server. [Details](deepseek-v4/maya-ds4-sycl/#decode-switches-2026-11-18-evening).
- **DeepSeek V4.1 Flash 1017 on Project Maya's `ds4` engine ported to SYCL: decode 29.3 tok/s (36.8 drafted), 8k prompt read ~280 tok/s.** Not live. Two days of port and hill climb on four cards; the llama.cpp fork yardstick is 3.92 / 0.65. Decode came from waiting for cross-card flags on the host before launching (a kernel already spinning on a host-USM flag never sees the write here: 0.03 -> 19.9 tok/s), drafter floors and 128-row SoA tiles for the dense Q6_K weights. The prompt read went 39 -> 280 tok/s with chunk 512, XMX sparse attention and XMX heavy-expert GEMMs, with the same output tokens throughout. Cards are busy ~26% of the read, so pipeline bubbles are the next lever toward 600. [maya-ds4-sycl](deepseek-v4/maya-ds4-sycl/).
- **JIT bug: stores from size-1 `joint_matrix` accumulator arrays are dropped.** The first heavy-down kernel wrote nothing; two roles fix it. [Details](deepseek-v4/maya-ds4-sycl/#jit-drops-stores-from-size-1-joint_matrix-arrays).
- **The Level Zero v2 adapter deadlock (`l0-deadlock`, intel/llvm#23530) hits the `ds4` port without oneMKL**: ~50% of 8k reads hang once the expert kernels got faster. A stack watchdog put every card's thread in `zeCommandListAppendLaunchKernelWithArguments`. The v1 adapter ran 7 of 7 and passed a serve-mode idle test with gaps up to 10 minutes (8k 281-288 tok/s, 2k 211). [Details](deepseek-v4/maya-ds4-sycl/#faster-kernels-expose-the-level-zero-v2-adapter-deadlock).

## 2026-11-17
- **Flash-Next prompt read +31%, live: grouped prompt experts on IQ3_S, on both cards, on the ESIMD GEMM.** Three changes in one Strata patch. Each layer now checks its own expert types, so IQ3_S (a quant mix) can use the grouped path at all. The expert-parallel card had never run it at `--prefill 8192`, because of a `T_max == 12288` pin; the pin is gone. And the grouped GEMMs run on the llama.cpp fork's ESIMD kernel (llama.cpp#31428 plus the GLM-5.3 IQ2_S loader and 64-wide tiles) through a small C shim. 32k read 1,680 -> 2,194 tok/s (timing off, 3 interleaved rounds), 8k 1,503 -> 1,947, decode unchanged, first 16 tokens at 32k identical. The abliterated entry: 1,547 -> 2,091 (+35%). On real traffic a 42k read went from 1,150-1,300 to 1,726 tok/s. Both Flash-Next entries run it; the old runtime and configs are kept for rollback. [ESIMD prefill](strata-windows-port/esimd-prefill/).
- **Flash-Next expert rebalance toward card 0: rejected.** With the patch the expert-parallel card idles ~11 s of a 19 s 32k read, but moving 0.40 / 0.33 / 0.25 of the traffic to card 0 is slower at every share: card 0's GEMM shrinks, its routing and combine waits grow more. [Tried and rejected](strata-windows-port/esimd-prefill/#tried-and-rejected).
- **Measurement note: `STRATA_PREFILL_TIMING` distorts two-card Strata runs.** It makes the host wait on the peer queue every layer, which swung card 0's "host grouping" from 1.6 to 5.7 s between identical runs. Speeds in this repo for Strata two-card prompt reads are now quoted with timing off.

## 2026-11-16
- **DeepSeek V4.1-Flash-1017 engine decision and draft-head findings reconciled (no build).** The open "which engine runs 1017 on 4x B70" question, answered against the repo and the current upstream state: the lab's proven new-model pipeline since 2026-11-01 is Project Maya, which has a complete in-tree 1017 engine (`src/ds4/`), so the recommendation is a Maya `ds4` SYCL port (option A') with the llama.cpp fork kept as yardstick; the 10-27 "Strata is the route" default predates the GLM port and is re-targeted, not reversed. The draft-head gating risk is cleared: the checkpoint ships a 3-block DSpark drafter (2,401 `mtp.*` tensors), the official Maya packs ship it as separate files, ds4 has first-class drafter support. The "current best" 1017 row now carries the 2026-11-12 warm baseline (3.92 decode / 0.65 prompt, 32k); the 11-05 single run is superseded. No build, no live change; awaiting owner sign-off. [Engine decision](deepseek-v4/engine-decision-2026-11-16/ENGINE-DECISION.md), [draft-head findings](deepseek-v4/engine-decision-2026-11-16/DRAFT-HEAD-FINDINGS.md).
- **GLM-5.3 card-to-card hand-off copy in the prompt read (L16): rejected.** VTune had it at 37-62 ms a call on the sending cards; timed on the host it is 18-21 ms out and 6-9 ms in, about 1.4 s a card over a 54 s 115k read, and fencing every copy costs nothing measurable. A 16-byte-a-work-item copy is 2% slower. Logits byte for byte as live throughout; nothing changed live. [Hand-off copy](glm-5.3/sycl-port/experiments/2026-11-16-chunk-sweep-and-profile/#hand-off-copy-l16).
- **GLM-5.3 prompt chunk re-sweep and profile of the live build: chunk stays 1536.** 2048 reads 115k ~6% faster but gives different logits run to run (1536 is byte-stable); 3072 / 4096 break the output (115k loss 0.23 -> 1.34 / 3.92) and one run crashed out of device resources. The profile shows the card-to-card hand-off copy on the sending cards at 37-62 ms a call, was ~5 ms on the L12 build: 9-13% of those cards' kernel time, new lead. Nothing changed live. [Chunk sweep and profile](glm-5.3/sycl-port/experiments/2026-11-16-chunk-sweep-and-profile/).
- **GLM-5.3 64-wide ESIMD tiles (L14) are live.** 30-minute mixed soak clean: 559 requests, no errors, answers as in the L5 soak, decode within 0.3%, cold 115k prime 61.4 -> 56.0 s. The engine config now runs the 64-wide build (backup kept); GLM reloaded and answered, cold 45.8k read 23.7 -> 21.5 s. [Soak and promotion](glm-5.3/sycl-port/experiments/2026-11-16-esimd-tile-sweep/#soak-and-promotion).
- **GLM-5.3 ESIMD grouped GEMM with 64-wide tiles (L14, measured).** At 288 experts and 8 a token a 1536-token chunk gives an expert about 43 rows, so 32-wide tiles dequantize most experts' weights twice. 64-wide tiles: cold 115k read -9.3%, 32k -8.4%, 8k code -5.6%, logits byte for byte as live. Skipping empty column blocks (L15) and 16-row threads lose. [Tile sweep](glm-5.3/sycl-port/experiments/2026-11-16-esimd-tile-sweep/).
- **GLM-5.3 XMX indexer for the prompt read (L5) is live.** 30-minute mixed soak clean on the candidate with the switch on: 543 requests, one answer per repeated request, no errors, cold 115k prime 65.1 -> 61.4 s against the L12 soak, cached follow-ups unchanged. The engine config now runs the candidate executable with `STRATA_GLM_DSA_XMX=1` (backup kept); GLM reloaded and answered, cold 45.8k read 24.3 -> 23.7 s. [Soak and promotion](glm-5.3/sycl-port/experiments/2026-11-16-indexer-xmx/#soak-and-promotion).
- **GLM-5.3 XMX indexer for the prompt read (L5, measured).** An f16 `joint_matrix` version of the DSA indexer score, after llama.cpp#31313 (keys packed once into shared memory, reused for every head and token block), in place of the FP32 tiled kernel: cold 115k read -5.3%, 32k -1 to -2%, 8k flat. Over 511 teacher-forced tokens the loss moves -0.2% (32k) and +0.7% (115k), within noise; a 64-token check had shown +2.5% on 32k. [XMX indexer](glm-5.3/sycl-port/experiments/2026-11-16-indexer-xmx/).
- **GLM-5.3 dense prompt projections on the ESIMD grouped GEMM (L13): rejected.** Routing the dense Q6_K products through the L12 kernel (64-token pieces sharing one weight) makes every chunk 27% slower (8k read 7.00 -> 9.27 s): the kernel dequantizes the weight again every 64 tokens, 22 times a chunk, where the old path dequantizes once and calls oneMKL. Nothing changed live. [Dense ESIMD](glm-5.3/sycl-port/experiments/2026-11-16-dense-esimd/).
- **GLM-5.3 prompt read re-profiled on the L12 build.** On a 115k read the grouped expert products are still 46-48% of the busiest cards' kernel time; attention 17-18%; the DSA indexer 10-11% (it grows with depth: 3% at 32k); the dense projections 8-12%, of which re-dequantizing Q6_K weights to f16 every chunk is about half. Card 3 runs 28% short of cards 0/1 during reads, but moving work to it would slow decode. Nothing changed live. [Prefill profile](glm-5.3/sycl-port/experiments/2026-11-16-prefill-profile/).
- **GLM-5.3 prompt read -22%, live: the ESIMD grouped expert GEMM of llama.cpp#31428 plus an IQ2_S format for it.** Promoted in two steps, each after a clean 30-minute soak. Step 1, the PR's kernel for the IQ3_XXS down product: cold 45.8k 31.2 -> 28.0 s. Step 2, an IQ2_S loader written here for gate/up (grid kept as 2-bit levels, 2 KB of shared memory): 28.0 -> 24.3 s; 115k 81.3 -> 63.7 s overall. Decode unchanged. In the kernel's bit-exact mode the new format gives the old build's logits byte for byte; the default mode shifts them about as much as the 1536-chunk change did. [ESIMD grouped GEMM](glm-5.3/sycl-port/experiments/2026-11-15-esimd-grouped-gemm/).

## 2026-11-15
- **GLM-5.3 prompt read -10% with the ESIMD grouped expert GEMM of llama.cpp#31428 (candidate, not live).** The PR's kernel dequantizes in registers for the matrix units, with no shared-memory staging. In the engine it covers the IQ3_XXS down product: cold 45.8k 31.2 -> 28.0 s, 115k 81.3 -> 73.1 s, decode unchanged, logits within the 1536-chunk change's shift. Gate/up (IQ2_S) needs a new loader. [ESIMD grouped GEMM](glm-5.3/sycl-port/experiments/2026-11-15-esimd-grouped-gemm/).
- **GLM-5.3 MTP draft vocabulary by token frequency: rejected.** The A/B ran: the 40k / 49k lists cut the draft 2.20 -> ~1.8 ms a step with the same acceptance and the same output, but decode does not move (code 54.6, prose 45.0 tok/s on every arm) because the step waits on the tail stage instead. The draft is not on the critical path. [Draft vocab](glm-5.3/sycl-port/experiments/2026-11-15-mtp-draft-vocab/#ab-2026-11-15).
- **GLM-5.3 expert gate/up kernel (L7): no in-place win.** Twenty bit-exact variants of the IQ2_S `moe_gate_up` kernel (16-bit code grid, split grid, 4+4 rows, aligned loads, per-lane bases) land at 0.77-1.03x of the live 126.7 us; the read floor is 81.7 us. The B70 ISA shows ~1,105 instructions a loop step for 32 `dp4a`, mostly 64-bit address packing and emulated multiplies, and the issue time matches the measurement. `dpct::dp4a` already compiles to native `dp4a`. A first row-per-lane rewrite spilled and ran 2.4-6x slower. All four cards run the kernel in 127-132 us alone, so card 3's slower in-engine time is an engine effect. Nothing changed live. [Gate/up kernels](glm-5.3/sycl-port/experiments/2026-11-15-moe-gateup-kernels/).
- **Level Zero loader 1.35.0 under the v2 adapter on Windows: both bugs remain; the barrier abort is in the GPU driver.** Loader 1.35.0 built from source (the Windows SDK has no DLL). It runs only with its own layers: by default it loads the System32 1.33.1 tracing layer, which rejects the 1.20 API (`ZE_RESULT_ERROR_UNSUPPORTED_VERSION`, 0 GPUs); `ZEL_LIBRARY_PATH` pointing at the new layers fixes that. With 1.35.0 under the oneAPI 2026.0 runtime, and again with the Unified Runtime v7.2.0 (loader + L0 adapters) built against it and forced in with `UR_ADAPTERS_FORCE_LOAD`, the cross-device barrier exchange aborts every run. The abort message comes from the Intel driver (`ze_intel_gpu64.dll`), so a newer loader or runtime cannot fix it. The multi-thread deadlock still occurs. [Reproducers](reproducers/README.md#parked-next-step-a-newer-level-zero-loader-under-the-v2-adapter).
- **GLM-5.3 MTP draft vocabulary by token frequency: candidate built, not measured.** The draft head reads 316 MB a draft today (ids below 98,304). Lists of the most frequent tokens of the lab's generated books and of public code cover held-out text with 0.4 / 5.9 misses per 1,000 (prose / code) at 158 MB; the 32k id cut tried on 2026-11-01 missed 86 / 82. New switch `STRATA_GLM_MTP_DRAFT_IDS=<file>` in a candidate engine; decode A/B pending a GPU window. [Draft vocab](glm-5.3/sycl-port/experiments/2026-11-15-mtp-draft-vocab/).

## 2026-11-14
- **GLM-5.3 decode +3.5%: aligned-load Q6_K mat-vec, live.** The dense one-column mat-vec reads each lane's weights as aligned 32-bit words (210-byte blocks are 0-3 bytes off) and takes two rows a warp: 8-14% faster per kernel, decode on code 52.2-52.9 -> 54.5-54.6 tok/s, output bit-exact. Two traps on the way: pack tensors at odd offsets, and FMA contraction under the engine's `-fp-model=precise`. [Aligned Q6_K](glm-5.3/sycl-port/experiments/2026-11-14-q6k-aligned-gemv/).
- **GLM-5.3 decode profile.** Every expert is VRAM-resident and decode is already a two-stage spec pipeline (CUDA0+1 / CUDA2+3); a step is the tail stage plus the MTP draft in series, and each card idles ~50%. VTune per-kernel time: routed experts ~27% of decode kernel time, dense GEMV ~55%; expert kernels at ~52% of bandwidth, dense at ~69%. A host-staged cross-card hop costs 19 us at 64 KB. Expert parallelism rejected; new decode leads L7-L11 ranked. Nothing changed live. [Decode profile](glm-5.3/sycl-port/experiments/2026-11-14-decode-profile/).

## 2026-11-13
- **GLM-5.3 prompt read: 1536-token chunks + 64k checkpoint spacing, live.** `--prefill 1536` with `STRATA_GLM_CKPT_EVERY=65536` cuts a cold 45.8k read 42.0 -> 32.4 s and a cold 115k read 103.7 -> 82.2 s (about -21%), decode unchanged, no PCIe staging. The larger chunk fills the grouped XMX tiles. Logits shift (32k top-1 62/64, KL 0.0129: the mixer and shared-expert sub-batches grow with the chunk) but true-next-token log-loss is the same (0.988 vs 0.985 on 63 tokens). 30-minute soak clean (57 cycles, 115k first read 82.8 s, edits ~0.51 s). Promoted at Jon's request; live smoke 45.8k in 34.9 s. [1536 chunks](glm-5.3/sycl-port/experiments/2026-11-13-prefill-chunk-1536/).
- **GLM-5.3 prompt read.** It is already pipelined across the four cards (equal chunks through the layer split; all four compute engines busy at once), so that lead is closed. The cost found instead is the checkpoint spacing: the engine reads a long prompt as separate calls every `STRATA_GLM_CKPT_EVERY` (16384) tokens and refills the pipeline each time. 65536 cuts a cold 45.8k read 40.3 -> 37.1 s (-8%) and a cold 115k read 101.3 -> 96.6 s (-5%); `0` gives 37.0 / 94.9 s; decode unchanged, two 16k controls within 0.2 s. Not live. Layer split moves are blocked by VRAM: 14,24,35 changed nothing, 13,24,35 ended in the driver crash. [Prefill screen](glm-5.3/sycl-port/experiments/2026-11-13-prefill-ckpt-screen/).
- Intel graphics driver 32.0.101.9175 on the test machine (was 32.0.101.8976). GLM and Strata run and answer correctly; the `ze_intel_gpu64.dll` access violation is not fixed (2 of 8 screen arms).
- GLM-5.3 slot buffer reuse: the 30-minute soak on the live build was clean (52 cycles, repeated 115k edits ~0.56 s, same answers as the resume soak). [Soak](glm-5.3/sycl-port/experiments/2026-11-13-slot-buffer-reuse/#soak).
- Strata with Unsloth UD-Q4_K_XL (Flash-Next) on the Windows SYCL port: the 2-card mode cannot hold its experts and the 1-card RAM mode outputs garbage, while the same file is correct in the llama.cpp fork. Rejected; IQ3_S stays. [STATUS](STATUS.md).
- GLM-5.3 Maya SYCL: parked two leads on existing data, no new runs. L2/L5 DSA scorer: the whole 2k→100k MTP decode gap is 5.1%, under the 8% deep-workload gate. [DSA ceiling](glm-5.3/sycl-port/experiments/2026-11-13-dsa-ceiling/). L3 full prompt memo: ~36 ms of CPU preparation in a 0.909 s 115k follow-up, ceiling ~3.7%. [Prompt-prep ceiling](glm-5.3/sycl-port/experiments/2026-11-13-prompt-prep-ceiling/).
- **Corrections.** Retracted the 2026-11-12 Windows numbers for [llama.cpp#32058](https://github.com/ggml-org/llama.cpp/pull/32058): the +9.3% nsm pp512 came from a depressed stock baseline, and the early "2-card" tables used `llama-bench -ts 1,1`, which runs two one-card configs (a real split is `-ts 1/1`). Clean rerun (3 rounds, 60 s idle): nsm neutral at short context; the patch's new fusions neutral vs stock with fusion on; graph on costs ~2.5% 1-card decode on both builds; fusion + graph crashes 1-card decode on both builds. [Discussion #32](https://github.com/Captain-Tripps/b70-lab/discussions/32).
- Patch files converted to LF (CRLF made `git apply` reject `meta-zero-noncompute-before-allreduce.patch`); `.gitattributes` keeps `*.patch` / `*.diff` LF.
- **GLM-5.3 turn trace.** Upstream Maya's server-side MAYA_TURN_TRACE marks, ported into an isolated server copy, plus the engine's slot timing on the live config: a 115k follow-up's first-token time is engine slot work, not the server. Found a 102 s full re-read on the first new-text edit after switching conversations and back: the switch drops the turn-start checkpoint and RAM slots do not carry it. A candidate that keeps checkpoints through the slot take-back was screened and rejected (no effect, all answer hashes match). [Screen](glm-5.3/sycl-port/experiments/2026-11-13-slot-keep-ckpts/). Carrying the turn-start checkpoint with the RAM slot instead fixes it: 102.27 -> 1.25 s median, all answer hashes match, returns ~60 ms slower. A 30-minute soak on the 2026-11-12 mix was clean (same answers and re-reads as that soak, slot switches ~40-55 ms slower); a soak with a new-text edit every cycle ran out of slots by count and hit the known driver crash at 21 minutes. Promoted at Jon's request ([record](glm-5.3/sycl-port/experiments/2026-11-13-slot-carry-ckpt/promotion.md)). It needs an unchanged return before the edit: an edit sent straight after a switch still re-reads. A candidate that takes back the slot whose carried checkpoint the prompt starts with covers that too: 101.5 -> ~1 s, all 16 answer hashes match. Promoted at Jon's request without a soak ([record](glm-5.3/sycl-port/experiments/2026-11-13-slot-ckpt-resume/promotion.md)); a 30-minute soak on the live build afterwards was clean (49 straight edits at ~1.03 s, same answers as the carry soak, no errors). [Resume screen](glm-5.3/sycl-port/experiments/2026-11-13-slot-ckpt-resume/). A 115k RAM slot save spent ~300 ms allocating and zero-filling a fresh 1.74 GB buffer and ~100 ms freeing one; reusing up to three dropped buffers (`STRATA_GLM_SLOT_REUSE=3`) cut the median save from 569 to 199 ms and repeated 115k edits from ~0.95 to ~0.56 s, all 29 answer hashes match. Promoted at Jon's request without a soak. [Buffer reuse](glm-5.3/sycl-port/experiments/2026-11-13-slot-buffer-reuse/). [Slot carry](glm-5.3/sycl-port/experiments/2026-11-13-slot-carry-ckpt/). [Turn trace](glm-5.3/sycl-port/experiments/2026-11-13-turn-trace/).

## 2026-11-12
- Locked in Xe2 `nsm = CUs / 8` (arch-aware BMG-G31) from [llama.cpp#32058](https://github.com/ggml-org/llama.cpp/pull/32058) / discussion #3: Windows A/B on Qwen3.8-27B 1 card (the +9.3% pp512 posted that day was retracted on 2026-11-13). Applied to fork (`proto/sycl-nway-allreduce` + `b70-r67`), live graph6-vcache rebuild, and patch [`nsm-xe2-bmg-g31-from-32058.patch`](llama.cpp-sycl/nsm-xe2-bmg-g31-from-32058.patch). Confirms the 2026-11-07 probe; still prefer `/8` over the TILE floor alone for upstream.
- Flash-Next MoE garbage on 3-card N-way all-reduce (AdamN1): meta backend skipped zeroing non-COMPUTE tensor-split slices on the backend allreduce path. Fixed in fork `proto/sycl-nway-allreduce` and patch [`meta-zero-noncompute-before-allreduce.patch`](llama.cpp-sycl/nway-allreduce/meta-zero-noncompute-before-allreduce.patch). [NWAY follow-up](llama.cpp-sycl/NWAY-ALLREDUCE-2026-11-08.md#follow-up-moe-garbage-on-n-way-flash-next-2026-11-12).
- Revisited [llama.cpp#28778](https://github.com/ggml-org/llama.cpp/issues/28778) after a stale-bot close: the TDR/OOM was covered by the merged BMG-G31 60% max-alloc workaround ([#28953](https://github.com/ggml-org/llama.cpp/pull/28953)); no local patch needed. Root cause remains open at [intel/compute-runtime#998](https://github.com/intel/compute-runtime/issues/998). Logged in [STATUS](STATUS.md) and [hardware notes](hardware-and-windows-notes.md#bmg-g31-single-allocation-ceiling-and-host-ram).

## 2026-11-11
- Atlas inspection: its CUDA Qwen Q4_K_XL model contains 61 IQ4_XS and 6 IQ4_NL tensors (~2.98 GB combined); the B70 SYCL reorder patches cannot be used directly on NVIDIA. [Notes](glm-5.3/sycl-port/experiments/2026-11-11-weight-reorder/#atlas-applicability).
- IQ2_S weight-reorder lead: Maya grouped XMX uses unreordered weights and lacks an IQ2_S planar reader. Isolated prototype compiled and a CPU byte round-trip passed; GPU parity and timing await free cards. [Weight reorder](glm-5.3/sycl-port/experiments/2026-11-11-weight-reorder/).
- RAM conversation-slot candidate: edited follow-ups improved in sequential 8k–130k screens; at 130k the three-run means were 2.542 s disk vs 1.245 s RAM. All 31 paired visible responses matched, including an image case. Multi-chat and 32k earlier-edit/retry were exercised; 30-minute soak and other gates remain open. [Validation](glm-5.3/sycl-port/experiments/2026-11-11-slot-validation/).

## 2026-11-10
- Long-follow-up slot screen: RAM-backed slots cut mean 115k edited follow-up TTFT from 2.334 to 1.224 s in three sequential samples per arm; a switch-back was 2.582 vs 0.519 s. Needs broader validation and memory checks. A slots-disabled arm hit a GPU-driver access violation during initial prefill; cause unknown. [Slot screen](glm-5.3/sycl-port/experiments/2026-11-10-slot-storage-screen/).
- Partial prompt-memo pilot passed exact token checks and cut CPU serialization time but did not establish a served 115k follow-up TTFT gain in three noisy samples per arm. Full upstream port unmeasured; no live change. [Prompt memo](glm-5.3/sycl-port/experiments/2026-11-10-prompt-memo-screen/).
- Selective prefill sub-batches: preserving recurrent and dense original batching with 768 elsewhere left one changed 32k top-token choice and no demonstrated prompt-time gain in a single screen. No live change. [Selective batches](glm-5.3/sycl-port/experiments/2026-11-10-selective-sub-batches/).
- Sub-batch diagnosis: the first observed layer-0 difference followed a batch-shaped FP16-input output GEMM; expert selections diverged later. Splitting only that GEMM did not restore 32k baseline logits. [Diagnosis](glm-5.3/sycl-port/experiments/2026-11-10-sub768-diagnosis/).
- Sub-batch 768 follow-up: 32k teacher-forced top-1 agreement was 60/64; baseline repeats were bit-identical to each other, as were candidate repeats. Two additional 8k inputs each agreed 64/64. The numerical difference remains unvalidated; live settings unchanged. [Validation](glm-5.3/sycl-port/experiments/2026-11-10-sub768-validation/).
- Grouped XMX 48-row screen: 13.4% fewer tiles, but the warmed 8k prompt time was only 0.55% below the surrounding control mean, too little to establish a gain. Synthetic outputs and 64 forced-position logits matched; no live change. [BN48 screen](glm-5.3/sycl-port/experiments/2026-11-10-bn48-screen/).
- Screened a 64-row grouped XMX tile. It made ~19% fewer tiles but reduced row occupancy to ~33%; warmed 8k prompt time was ~17.5% worse, with 4.1M synthetic outputs and 64-position logits matching. Rejected at screening. [BN64 screen](glm-5.3/sycl-port/experiments/2026-11-10-bn64-screen/).
- Screened a narrower 16-row grouped XMX tile. It raised row occupancy but created ~47% more tiles and took about 17% more prompt time in the warmed 8k screen; 64-position logits matched. Rejected at screening; no live change. [BN16 screen](glm-5.3/sycl-port/experiments/2026-11-10-bn16-screen/).
- Profiled the GLM grouped XMX expert path at 8k: matrix spans dominate packing and tile-copy spans; row occupancy suggests a narrower-tile hypothesis. Two instrumented passes and off controls matched 64-row baseline logits; no live change. [XMX profile](glm-5.3/sycl-port/experiments/2026-11-10-xmx-profile/).
- Split the dominant GLM resident-expert prefill interval into grouped gate/up + SwiGLU, down product and row-gather event spans, with a profiler-off control and matching 64-position logits. Two [profiles](glm-5.3/sycl-port/experiments/2026-11-10-resident-profile/) identify the grouped products as the next place to investigate; no optimization or live change.
- Recorded the first GLM Maya SYCL [optimization screens](glm-5.3/sycl-port/experiments/2026-11-10-screening/): profiler-off and profiler-on projection measurements, a DSA operator parity and warm-cache timing fixture, full-model DSA checks, and the sub-batch comparison with its quality and headroom limitations. Corrected the served example's stale prefill chunk to 768. No candidate was promoted or live configuration changed.

## 2026-11-09
- Added a [GLM Maya SYCL optimization handoff](glm-5.3/sycl-port/LEADS-2026-11-09.md) for the next agent: six ranked leads, pinned source evidence, baseline and harness setup, experiment steps, correctness checks and stop/keep gates. Covers prefill projection batching, existing decode attention variants, incremental prompt preparation, sub-batches/checkpoints, remaining XMX paths and resident routing/fusion. Linked from the GLM notes and marked the old roadmap historical. Documentation only: no new B70 measurements or live changes.

## 2026-11-08
- N-way all-reduce follow-up for 92es: a 2-D all-gather launch and fixed-card-count sums are worth 0-2% (reduce kernels are ~2% of an all-reduce here; patch v2 keeps them). On 2 cards, uploading straight from the other card's pinned buffer reads prompts ~18% faster than the 4-buffer exchange #30956 uses on Windows, decode equal. Means of 3 clean rounds. [NWAY-ALLREDUCE-2026-11-08.md](llama.cpp-sycl/NWAY-ALLREDUCE-2026-11-08.md#follow-up-kernel-tweaks-and-the-4-buffer-exchange-2026-11-08-evening).
- 3/4-card `-sm tensor` all-reduce for ggml-sycl, roughed out for 92es (discussion #3), as a patch on the llama.cpp#30956 head. 4 cards read prompts at ~955 tok/s instead of 110 on the old generic fallback (layer split ~1,020), perplexity equal; decode 9.1 vs layer 17.3, so per-token syncs stay the cost. Direct card-to-card copies are no faster than the old fallback here. [NWAY-ALLREDUCE-2026-11-08.md](llama.cpp-sycl/NWAY-ALLREDUCE-2026-11-08.md).

## 2026-11-07
- Strata prompt-read lottery fixed, the same kind of leak as the decode one. With EP reduce on, card 1's 800 MiB rows buffer is never read by card 0, but it was allocated as a shared exchange region, which on Windows is host memory. It is now private VRAM. A 37k-token prompt reads at 1,476-1,570 tok/s on every start (first token ~24 s), against 774-780 on the old allocation; decode and greedy output unchanged. [slow-starts](strata-windows-port/slow-starts/#second-leak-the-prompt-read-2026-11-07).
- Strata slow starts, real cause found and fixed. With EP psum, card 0's own expert rows were written into the exchange region, which this Windows port has to allocate in host memory, and the combine read them back over PCIe. Keeping them in VRAM: 8 of 8 fresh starts at 104-108 tok/s (median 106.4) vs 54-83 on the old path, greedy output identical; ~30% above the old fast starts too. Found with per-stage stamps on both cards (card 1's side and the handshake were identical across starts). The 11-01 file-cache theory was a side effect, and its restart-if-slow guard and standby purge are retired. Patch in [slow-starts](strata-windows-port/slow-starts/#cause-and-fix-2026-11-07), sent upstream as [hotschmoe/Strata#1](https://github.com/hotschmoe/Strata/pull/1).
- Windows check of two changes proposed by 92es in discussion #3. The `nsm` / 8 fix for Xe2 gets most of the fork's TILE split-floor gain: Mistral-Small-3.2 decode at 32k +16.6% vs stock (floor +18.4%), Qwen3.8-27B +4.6% (floor +5.4%), perplexity unchanged. The per-dtype oneDNN probe is correct on B70 but no faster. [NSM-AND-DNNL-PROBE-2026-11-07.md](llama.cpp-sycl/NSM-AND-DNNL-PROBE-2026-11-07.md).
- Replication gaps filled, so both daily recipes can be rebuilt from this repo:
  - **Strata Flash-Next:** how to build the pack and the MTP draft layer (`iq_pack.py`, `mtp_fetch.py`, `mtp_pack.py`,
    `mtp_rt.py`), and where the draft vocabulary and expert profile come from (they ship in the Strata checkout). Also
    the abliterated variant and vision at 1024 image tokens.
    [strata-windows-port](strata-windows-port/#how-to-run-it).
  - **GLM SYCL port:** the serving pieces added after 11-01, namely Maya's server and the llama-swap entry, a patch that
    turns pictures into text notes when there is no vision encoder, the CPU vision encoder, `STRATA_GLM_RESERVE_MB=400`,
    and the GPU keep-alive. [glm-5.3/sycl-port](glm-5.3/sycl-port/#serving-it-added-2026-11-07).
- Upstream Strata v0.2.12 helper-card fix (32.1 -> 61.3 tok/s served) sent as Niko1221/Strata#5540.
- The llama.cpp Flash-Next entries were retired on 2026-11-06; [flash-next](flash-next/) is kept as the reference.

## 2026-11-05
- DeepSeek V4.1 Flash 1017: converted the older GSQ-RCO pack and an isolated copy of its Engram tables to the upstream llama.cpp layout. The converted 4-B70 SYCL run gave 1.505 tok/s warm decode and 10.287 prompt in one smoke test. The earlier no-Engram 18-layer run gave 2.730 / 15.237, but used a different physical drive and settings; parity and bottleneck remain unmeasured. Owner target: at least 50 tok/s. [Results and next tests](deepseek-v4/strata-v41/RESULTS-2026-11-05.md).
- Freed the full system drive by moving older Remote Desktop diagnostic traces to a preserved archive on D:; 131.80 GiB moved. Storage capacities in the results are point-in-time.

## 2026-11-01
- GLM-5.3-Flash: Project Maya's CUDA engine ported to SYCL / Level Zero on native Windows, 4 cards, now the live
  GLM entry: decode 24-25 (llama.cpp fork) -> 45.5-45.8 tok/s, 8k prompt read 309 -> 966-996 tok/s, 128k context.
  36 fix rounds over two days; the scripts, the shim header, the post-round-31 patch, benchmarks and the eight Level
  Zero / Windows rules found on the way are in [glm-5.3/sycl-port](glm-5.3/sycl-port/). Rejected with numbers: KDA
  SYCL graphs, int8 XMX expert GEMM, multi-token draft windows, batched command lists. The llama.cpp-fork GLM entry is
  retired.
- Strata slow starts: cause found. Windows' standby list (file cache) filling RAM makes the expert-parallel exchange
  ~4x slower; purging it before each start gave 8 of 8 fast starts vs 0 of 8 in the same hour. A reboot alone and a
  clean engine stop do not fix it. The served entry now runs a restart-if-slow guard that purges before a retry.
  [strata-windows-port/slow-starts](strata-windows-port/slow-starts/).
- Brought over the 2026-10-29 correction of the served `--adapt-every 0` result (it was one slow start), which had
  stayed on a side branch.
- From 2026-10-29, not written up elsewhere: Strata v0.2.8 built from source on Windows (no Windows SYCL package
  ships): its layer split gives a steady 55.0-57.5 tok/s median on 2 cards, below the lab build's fast starts (served
  entry unchanged). A community Gemma 4 26B-A4B Q8 recipe (llama.cpp b9769 + fused MoE kernels,
  [steveseguin/b70-optimization-lab](https://github.com/steveseguin/b70-optimization-lab)) on Windows: 85.7 tok/s median
  on UD-Q8_K_XL + MTP vs 60.1 for the single-card Q4 entry; Windows needs `/EHsc` kept in `CMAKE_CXX_FLAGS`, and its
  fused MoE down kernel crashes on non-Unsloth Q8 layouts.

## 2026-10-29
- Corrected the 2026-10-28 served `--adapt-every 0` result: served Strata speed is set per start and varies 58-100 tok/s
  with or without the flag, so the "99-104 -> 38-40" was one slow start. No clear served effect; config unchanged.
- Same-day head-to-head through llama-swap, cold requests, thinking off: Strata (2 cards) 84.2 vs llama.cpp Flash-Next
  MTP (4 cards) 50.4 tok/s median. A slow state (~39 tok/s on every start) after RAM exhaustion was cleared by a reboot.
  [STRATA-ADAPT-TIER](work/strata-v41-agent-runner/STRATA-ADAPT-TIER.md).

## 2026-10-28
- DeepSeek V4.1 Flash 1017 on the llama.cpp SYCL fork: first real numbers. Best 2.46 tok/s decode / 12.7 prompt read
  (`-ncmoe 24 -t 46` plus one `EmptyWorkingSet` after load); CPU-only 1.65, so the CPU expert layers are the
  bottleneck. [mirror-probe](work/strata-v41-agent-runner/mirror-probe/README.md).
- Found why Windows holds ~1 GB of host RAM per GB on the GPUs: llama.cpp's Windows `unmap_fragment()` is a no-op;
  the driver only reserves commit (standalone Level Zero probe). RAM watchdog made commit-aware.
- Strata `--adapt-every 0`: +49% in CLI `generate` (v0.2.7) but served decode on the lab build drops 99-104 -> 38-40;
  served config unchanged. RemoteExperts spin/host-metadata patch: no gain.
  [STRATA-ADAPT-TIER](work/strata-v41-agent-runner/STRATA-ADAPT-TIER.md).

## 2026-10-26
- Added STEP-000 to qualify DeepSeek V4.1 Flash 1017 through OpenRouter/OpenClaw with a native Windows runner,
  CPU-only lifecycle mocks and session resume. Added a copyable [agent starter prompt](deepseek-v4/strata-v41/OPENCLAW-START.md).
  Coding inference is remote; no coding-model swapping is required. Integration and hardware checks remain NOT_RUN.
- Added the [Strata DeepSeek V4.1 four-B70 Windows action plan](deepseek-v4/strata-v41/PLAN.md) with pinned upstream/lab
  evidence, source-backed decisions, ordered work packages and acceptance gates. It reuses the existing Windows
  port and records known driver/compilation failures; no GPU tests or performance measurements were run.
- Superseded the old Track B wait-for-llama.cpp prerequisite for this Strata route, retained the V4 0731
  expert-parallel rejection, and made current RAM/hardware reconciliation the first gate. Historical hardware
  entries and production configurations are unchanged.

## 2026-10-25
- Review notes on @92es's startup-selected barrier exchange: the context check alone would select the barrier path on
  Windows and crash on the default L0 v2 adapter; the trailing upload waits are needed with one staging pair (safe to
  drop with two); `nsm` undercounts Xe2 cores (arch-aware fix + re-measure); the oneDNN probe is fine on B70.
  [TENSOR-SPLIT-DECODE.md](llama.cpp-sycl/TENSOR-SPLIT-DECODE.md#review-notes-on-the-startup-selected-barrier-exchange-2026-10-25).

## 2026-10-24
- Queue-barrier exchange on Windows, cause found: the two devices already share one SYCL context; the abort comes from
  the Level Zero v2 UR adapter, and the legacy adapter (`SYCL_UR_USE_LEVEL_ZERO_V2=0`) runs it (standalone test).
  **Corrects** an earlier entry today that blamed separate contexts / `SYCL_ENABLE_DEFAULT_CONTEXTS` being off on
  Windows. No speed numbers yet.
  [TENSOR-SPLIT-DECODE.md](llama.cpp-sycl/TENSOR-SPLIT-DECODE.md#shared-context-attempt-windows-2026-10-24).
- @92es (Linux): `SYCL_ENABLE_DEFAULT_CONTEXTS` flips shared vs separate contexts there; KL divergence of the barrier
  patch vs stock identical at ub 4, within noise at ub 512.

## 2026-10-23
- Graph cache validated in llama-server and switched live for the 2-card dense models: Mistral-24B decode +45%,
  Qwen3.8-27B Q8 / Q6 +18-21% (now tensor split instead of layer), PPL ub4 bit-exact. Record-size gate must be 512
  (8 loses most of the gain; recording large batches crashes on the oneMKL flash-attention path).
- New SYCL get_tensor_2d removes 10-35 s slot-save stalls in tensor split (slot save at ~15k tokens 35 s -> 1.1 s).
- Cache + per-card launch threads rejected for serving (1 exit + 1 hang in 6 runs).
- Long-form generation workload: Qwen3.8-27B Q6 1 card -> 2-card tensor + cache, decode +26-41%, wall -24%. The
  paired Gemma 4 26B-A4B moved to the rebased runtime on its single card: decode +30-40%.
  [TENSOR-SPLIT-DECODE.md](llama.cpp-sycl/TENSOR-SPLIT-DECODE.md).
- Community results from @92es (Linux, single SYCL context): the queue-barrier exchange runs there, ub-4 PPL
  identical to stock, +15% at ub 512. Retested the exact peer-only wiring on Windows: still aborts (separate
  contexts per device).

## 2026-10-22
- Mistral-Small-3.2-24B (the only 2-card tensor-split entry) switched live to r67c + PR #30956.
  [PR30956-2026-10-21.md](llama.cpp-sycl/PR30956-2026-10-21.md).
- Qwen3.8-27B 2-card `-sm tensor` + PR #30956 vs layer split (MTP, A/B/B/A): prompt read equal, decode -18%; both
  entries stay on layer split. [PR30956-qwen27-2026-10-22.md](llama.cpp-sycl/PR30956-qwen27-2026-10-22.md).
- New working page on the tensor-split decode gap: llama-bench by batch size shows tensor split 19-33% slower than
  layer at 1-8 tokens with or without #30956 (the PR only helps pp512); ~40 ms per forward lost to the split vs an
  ideal ~28 ms. Theory (host waits per all-reduce), candidate fixes and an MTP A/B method.
  [TENSOR-SPLIT-DECODE.md](llama.cpp-sycl/TENSOR-SPLIT-DECODE.md).
- Timers: the tensor-split decode gap is single-thread kernel launch (41.5 ms per forward), not the exchange waits;
  exchange fixes cap at layer parity. A per-subgraph SYCL graph cache (prototype, env-gated) removes ~30 ms of it:
  2-card tensor split pp1 / pp5 / tg +35% / +32% / +30% over layer on Qwen3.8-27B, ub-4 perplexity bit-identical.
  Stock graph mode crashes in the Level Zero driver. Server and MoE tests pending.
- Per-card launch threads now run with `UR_L0_V2_DISABLE_ZE_LAUNCH_KERNEL_WITH_ARGS=1` (avoids the Level Zero
  two-thread launch deadlock). On top of the graph cache: pp1 +40-42%, pp5 +35-37%, pp512 +31%, tg +38% over layer
  split; ub-4 perplexity bit-identical, four bench loops clean. Without the cache: one oneMKL crash in four loops.

## 2026-10-21
- Tested upstream PR #30956 (fast 2-device `-sm tensor` exchange) on r67c: correct on Windows Level Zero (ub-4
  perplexity bit-identical); Mistral-Small-24B tensor split prompt read +14%, decode +2%; gpt-oss-120b tensor prompt
  +5%, decode equal (3-card layer split still ~2x faster). Found: `GGML_SYCL_PIPELINE=1` + `-sm tensor` makes gpt-oss
  emit garbage (not the PR). [llama.cpp-sycl/PR30956-2026-10-21.md](llama.cpp-sycl/PR30956-2026-10-21.md).

## 2026-10-18
- r67c also live for DeepSeek V4 (no draft; DSpark + lookup), Qwen3.8-27B Q8_0 and Q6_K, and Flash-Next MTP + lookup;
  answer checks pass on every switched entry. Only GLM-5.3 and the plain Flash-Next MTP entry stay on older runtimes.
- r67c switched live for DeepSeek V4 Flash DSpark and gpt-oss-120b (smoke: 20.7k-token prompt read at 651 tok/s,
  answers correct). GLM-5.3 and the Flash-Next llama.cpp entry stay on their old runtimes (neutral).

## 2026-10-17
- llama.cpp fork rebased onto upstream master of 2026-10-17 (r67c, staged): DeepSeek V4 prompt read +36% at 33.6k and
  decode +5%, gpt-oss-120b decode +7%, GLM-5.3 and Flash-Next neutral; answers correct and perplexity equal on all
  four. Upstream's Q5_K kernel and Flash-Next MTP head replace the fork's; two local fixes let the MTP head load from
  a shared-weights draft file ([notes](llama.cpp-sycl/REBASE-2026-10-17.md)).
- Strata Windows patch set complete (0001-0004; 0004 = optional timer-resolution switch, no measured effect); a
  how-to-run recipe (JIT build, config essentials, CPU vision encoder, llama-swap entry) in strata-windows-port/.
  Current best for Flash-Next recorded at the top of STATUS.md.
- Strata 2 slots x 112k vs 1 x 200k: +17% aggregate with two concurrent streams, but -37% prompt read and 88k less
  context; 1 x 200k stays the default.
- Strata slow starts (~70 instead of ~98 tok/s) traced to `--ple-io direct`: unbuffered SSD reads of the 27 GB PLE
  table every token, slowed by drive latency after ~130 GB of writes. `--ple-io mmap` restores ~99 tok/s; the
  published best config now uses it. MTP draft sweep: upstream defaults (`--spec 4`, p-min 0) stay.
- DeepSeek Track A step A0: expert matmuls are 14% / 22% of decode op time, ceiling 1.12x plain / 1.19x DSpark;
  expert-only parallelism rejected. Track B (V4.1) stands.
- Strata 2-hour soak through llama-swap (IQ3_S, 1 x 200k, vision on): 134 cycles, 0 errors, 0 restarts, answers and
  vision 134/134, decode 93.0 tok/s median with no drift, 112k-token prompt at ~1,430 tok/s.
- DeepSeek plan updated: Track A = expert parallelism for V4 Flash 0731 in the llama.cpp fork (go / no-go after a
  1-hour profile); Track B = DeepSeek V4.1 Flash 1017 (released today, new ~510B architecture, not in llama.cpp yet),
  watching for support ([plan](deepseek-v4/PLAN-expert-parallel.md)).
- Quant quality: GSQ-RCO IQ3_S perplexity +1.0% / mean KLD 0.131 / same top token 88.4% vs IQ3_XXS +3.5% / 0.211 /
  85.3% (reference UD-Q4_K_XL).
- New best Strata setup: IQ3_S, 2 cards, 1 x 200k, int8 KV, prefill chunk 8192, JIT: decode 97.6 tok/s (+61% vs
  llama.cpp on 4 cards), prompt read 1,415 tok/s at 33.6k (1.9x), decode after it 64.9 (2.3x). IQ3_XXS superseded.
- Strata prompt chunk sweep (IQ3_S, 1 x 200k): 8192 kept (1,417 tok/s at 33.6k; 112k-token prompt at 1,433 tok/s,
  decode after 72.2); 10240 sits at card 1's memory limit and runs ~3x slower; 12288 does not fit.
- `STRATA_NIGHT_PREFILL_GROUPED` must be 0 for IQ3_S (unsupported type); prompt chunk 4k -> 8k: 881 -> 1,415 tok/s.

## 2026-10-16 (late)
- Parked plan added: Strata-style expert parallelism for DeepSeek V4 Flash ([plan](deepseek-v4/PLAN-expert-parallel.md)).
- Strata int8 KV bug on Windows solved: oneAPI 2026.0's AOT build (`ocloc`, `bmg-g31`) miscompiles the batched
  decode attention over int8 KV; the same sources JIT-compiled by the driver pass parity bitwise. Patch 0003 adds a
  JIT build switch. Strata 2 cards, int8 KV, 200k x 2 slots: 108.2 tok/s vs llama.cpp r62 on 4 cards 60.6 (+79%),
  answers correct. The earlier 96.6 tok/s AOT number was invalid; the fp16-KV result is superseded.

## 2026-10-16
- Repo created from the existing notes, patches and reproducers.
- Strata engine ported to native Windows (patches 0001 / 0002). 2 cards, fp16 KV: answers correct, 67.4 tok/s vs
  llama.cpp r62 on 4 cards 60.6. int8 KV gives wrong answers on Windows (open bug). Level Zero on Windows: no IPC and
  no peer access between B70s; host USM in one shared context works.

## 2026-10-15
- Expert-overlap study (Flash-Next 42%, GLM 30%, DeepSeek V4 32% redundant expert assignments in a verify window).
  Grouped expert verification kernel: -5 to -10%, rejected.
- Client-side prompt-cache priming for long shared prefixes on recurrent-state models: ~154 s -> ~64 s of prompt
  work on a 5-request job.

## 2026-10-14
- GLM-5.3-Flash Maya-M live on the SYCL fork (g10): 16.5 -> 24-25 tok/s, 128k context with one expert layer in
  system RAM, MTP n4 / p0.75, reasoning effort high + 8k budget.

## 2026-10-12
- Flash-Next on r62 (top-k MoE single work-group, small fusions): ~61 tok/s. Q8_0 MoE reorder (r56) +4.9%.
  Qwen3.8-27B Q6_K / Q5_K wide dot (r64-r66).
- SYCL graph replay retried with an FA skip: runs, ~3x slower. Rejected.

## 2026-10-11
- r53 (F32 mat-vec for 2-8 columns): Flash-Next +10.5%. MTP n4 / p0.1 adopted.
- GPU driver 32.0.101.8805 -> 32.0.101.8976: prompt reads ~1.6-2.4x on the pipeline runtimes. Level Zero deadlock
  still reproduces.
- `set_tensor_2d` submitted upstream ([#30358](https://github.com/ggml-org/llama.cpp/pull/30358)).

## 2026-10-10
- MXFP4 SWAR decode + MoE reorder merged upstream ([#29809](https://github.com/ggml-org/llama.cpp/pull/29809)).
- Level Zero multi-thread submit deadlock reproduced in a standalone program.

## 2026-10-06
- Cross-card pipeline (r52, bounded queues) live for DeepSeek V4, Flash-Next and gpt-oss-120b: prompt reads ~1.6-2.3x.

## 2026-10-05
- DeepSeek V4 deep context: sparse FA fixed (memset ordering) + oneMKL indexer (r27).

## 2026-10-03
- Local-memory IQ2_XS / IQ3_XXS MoE kernel for DeepSeek V4: DSpark 18.5 -> 24.2 tok/s. Routing fusion +2%.

## 2026-10-01
- Idle VRAM eviction found and fixed with a GPU heartbeat. `GGML_SYCL_ENABLE_DNN=0` for prompt reads. QSA pool
  fusion for Flash-Next at depth (+23%).

## 2026-09-30
- Machine moved to 4x B70 and an EPYC 7402P host. Pinned `-sm tensor` all-reduce merged upstream
  ([#29604](https://github.com/ggml-org/llama.cpp/pull/29604)).

## 2026-09-27
- First B70 tuning on 2 cards: Q8_0 16-byte loads, flash-attention split 48, MXFP4 reorder, GLU and ADD+RMS fusions.
