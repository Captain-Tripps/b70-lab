# Why 2-card `-sm tensor` decodes slower than `-sm layer` on SYCL (working notes)

Living page, started 2026-10-22. Collaboration welcome: open an issue or a discussion in this repo with numbers
from your own cards. Upstream context: [ggml-org/llama.cpp#30956](https://github.com/ggml-org/llama.cpp/pull/30956)
(faster exchange, by @92es) and the thread on [#30358](https://github.com/ggml-org/llama.cpp/pull/30358).

**Update 2026-10-22 evening: a per-subgraph SYCL graph cache removes most of the launch cost. 2-card tensor split now
decodes ~30% faster than layer split on Qwen3.8-27B ([Measurement 3](#measurement-3-per-subgraph-sycl-graph-cache-2026-10-22)),
and adding per-card launch threads on top brings it to +38-42% at 1-8 tokens and +31% at 512 tokens
([Measurement 4](#measurement-4-graph-cache--per-card-launch-threads-2026-10-22)).
Prototype, not yet tested in a server or on MoE models.**

## The question

On 2x B70, tensor split now reads prompts as fast as layer split (with #30956), but decode, and MTP decode in
particular, stays 18-21% slower ([PR30956-qwen27-2026-10-22.md](PR30956-qwen27-2026-10-22.md)). Is that a hardware
limit, or a cost in the backend that can be removed?

In principle tensor split should *win* decode: with layer split the two cards run one after the other, so a token
costs one full read of the weights at one card's bandwidth. With tensor split both cards read half the weights at the
same time, so the ideal is about half the time per token, plus the all-reduce cost.

## Measurement 1: per-forward cost by batch size (2026-10-22)

Decode and MTP verification are small batches (1 token, or draft + 1 = 5 tokens with `--spec-draft-n-max 4`).
llama-bench `-p N` times exactly one forward over N tokens, so it measures the cost side without MTP acceptance noise.

Qwen3.8-27B Q8_0, 2x B70, Windows, Level Zero, `-fa 1 -ctk q4_0 -ctv q4_0 -b 2048 -ub 1024`, no `GGML_SYCL_PIPELINE`.
r67c = the fork on upstream `797de63b2` ([REBASE-2026-10-17.md](REBASE-2026-10-17.md)); "+PR" = the same build with
only `ggml-sycl.dll` swapped for a hand port of #30956. tok/s, mean +- sd (r=5 at depth 0, r=3 at depth 32768).

| test | layer r67c | tensor r67c | tensor +PR | tensor vs layer |
|---|---:|---:|---:|---:|
| pp1 | 17.92 +- 0.12 | 14.45 +- 0.21 | 14.08 +- 0.15 | -19% |
| pp2 | 34.02 +- 0.12 | 26.85 +- 0.21 | 25.37 +- 1.85 | -21% |
| pp5 (MTP verify shape) | 83.93 +- 0.27 | 60.65 +- 3.23 | 63.31 +- 3.32 | -25..-28% |
| pp8 | 131.39 +- 0.10 | 88.20 +- 0.32 | 84.11 +- 10.96 | -33% |
| pp512 | 974.10 +- 1.72 | 897.69 +- 16.41 | 954.43 +- 12.08 | -8% (PR: -1%) |
| tg32 | 17.95 +- 0.06 | 14.13 +- 0.64 | 13.42 +- 1.32 | -21% |
| pp1 @ d32768 | 12.91 +- 0.35 | 10.15 +- 2.50 | 10.19 +- 2.09 | -21% |
| pp5 @ d32768 | 59.74 +- 1.47 | 45.84 +- 16.29 | 46.84 +- 9.01 | -22% |
| tg32 @ d32768 | 13.22 +- 0.01 | 12.41 +- 0.24 | 12.05 +- 0.32 | -6..-9% |

Layer numbers with the PR build were the same as r67c (the PR only touches the tensor-split exchange).

```
llama-bench -m Qwen3.8-27B-Q8_0.gguf -ngl 99 -sm layer,tensor -fa 1 -ctk q4_0 -ctv q4_0 -b 2048 -ub 1024 -t 8 \
  -p 1,2,5,8,512 -n 32 -d 0 -r 5
llama-bench ... -p 1,5 -n 32 -d 32768 -r 3
```

### Reading

- #30956 is a large-batch fix: pp512 tensor +6%, now level with layer. At 1-8 tokens it changes nothing beyond noise.
- Tensor split loses 19-33% at every decode/MTP-sized batch, with or without the PR.
- Size of the loss: layer pp1 = 55.8 ms per forward. Ideal tensor = about half (~28 ms). Measured tensor pp1 = 69 ms,
  so **~40 ms per forward goes to the split itself**. That is the headroom: recovering half of it would put tensor
  decode roughly 30-60% above layer on 2 cards.
- Tensor rows have 5-15x the run-to-run spread of layer rows, which fits host-side synchronisation jitter.
- The gap grows from pp1 to pp8 (13 -> 30 ms per forward over layer at depth 0), so it is not purely a fixed latency.
  One candidate: the all-reduce switches from the FP32 path to the BF16 path at 32K elements (hidden size 5120 x 7+
  tokens crosses it), adding two kernels per all-reduce. Unmeasured.

## Measurement 2: where the ~40 ms goes (2026-10-22, env-gated timers in a local build)

**The first theory (host waits in the exchange) was wrong. The gap is kernel launch on a single host thread.**

Per forward at pp1, median of 100 forwards (tensor 71.4 ms, layer 55.7 ms):

| host time, tensor split pp1 | ms per forward |
|---|---:|
| launching kernels, card 0 then card 1 on the same thread | 21.2 + 20.3 = **41.5** |
| inside the all-reduce (128 per forward = 2 per layer x 64 layers, ~186 us each) | 23.7 |
| of which host waits | 18.5 (mostly the GPU finishing the kernels launched just before; the copies themselves wait ~2.4 ms) |
| other (graph prep, outputs) | ~6 |

- With tensor split each card runs every layer: ~4,000 compute nodes per card per forward at ~5 us per launch. With
  layer split each card launches ~2,000 nodes and the launch time hides behind GPU time; with tensor split the
  end-of-forward sync waits ~0 ms, i.e. **the GPUs sit idle waiting for the host to launch work.**
- pp1 and pp5 use the FP32 all-reduce path; pp8 crosses the 32K-element threshold to the BF16 path (~1.5 ms more per
  forward).

Bounds (timing experiments that deliberately produce wrong results):

| test | layer | tensor | tensor, copies kept but no host waits | tensor, no all-reduce at all |
|---|---:|---:|---:|---:|
| pp1 | 17.94 | 14.00 | 18.00 | 20.8-21.4 |
| pp5 | 84.39 | 65.00 | 84.88 | 96.5-98.7 |
| pp8 | 131.90 | 103.40 | 130.84 | 148-153 |
| tg32 | 17.99 | 14.59 | 19.22 | 20.4-22.0 |

Removing every host wait only brings tensor to **parity** with layer at 1-8 tokens. Even a free all-reduce gives
only +16-19% at pp1, because ~44 ms per forward of pure launch time remains.

## Measurement 3: per-subgraph SYCL graph cache (2026-10-22)

Measurement 2 says the GPUs wait on ~41.5 ms of single-thread kernel launches per forward. SYCL graph replay removes
per-kernel launches, so it was the next thing to try.

**Stock graph mode (`GGML_SYCL_ENABLE_GRAPH=1`) is not usable here.** In llama-bench it "exits silently": the process
dies with a fast-fail (0xC0000409) inside the Level Zero driver (`ze_intel_gpu64.dll`), and llama-bench mutes the log
without `-v`. Just before that, two SYCL exceptions are thrown and caught in the graph path (consistent with the
executable-graph `update()` failing and falling back to `finalize()`). Where it survives, it re-records every call
and keeps one executable graph per context: layer pp1 6.3 tok/s vs 17.9 eager.

**Prototype: cache one executable graph per subgraph** (local, env-gated change in
`ggml_backend_sycl_graph_compute`, enabled with `GGML_SYCL_ENABLE_GRAPH=1 GGML_SYCL_GRAPH_CACHE=1`):

- Key: (backend context, first node of the subgraph) plus a signature of every node (op, type, flags, shapes, strides,
  data pointers, op params and the same for each source).
- First sighting runs eagerly (lazy weight reorders happen there). The second records and finalizes. After that the
  subgraph is replayed without recording and without per-node launches while the signature matches; a mismatch goes
  back to eager and re-records.
- Tensor-split decode uses ~258 entries per card, 0 misses in steady state. Recording a new shape costs ~0.4 s once
  (~129 subgraphs per card). Entries are freed with the backend.

Same model and settings as Measurement 1, tok/s, median of reps 3-8:

| test | layer eager | tensor eager | **tensor + graph cache** | vs layer | layer + graph cache |
|---|---:|---:|---:|---:|---:|
| pp1 | 18.06 | 14.13 | **24.45 / 24.69** | **+35-37%** | 17.92 |
| pp5 (MTP verify shape) | 84.39 | 68.47 | **110.35 / 112.45** | **+31-33%** | 83.27 |
| pp8 | 131.54 | 105.41 | **168.76 / 175.32** | **+28-33%** | 130.40 |
| tg32 | 17.95 | 14.64 | **22.88 / 23.88** | **+27-33%** | 17.61 |

(Two runs for the cache column.) pp1 goes from 70.8 to 40.9 ms per forward: about 30 of the ~41.5 ms of launch time
is gone. Layer split gains nothing, as expected: its launch time was already hidden behind GPU time.

Correctness, 2-card tensor split, 8 chunks of 512: perplexity at ub 4 is **bit-identical** to the stock build on
every cache run (4.8336, all chunk values equal), and faster (6.7-7.4 s vs 9.4-9.7 s per pass). At ub 512 tensor
split is not reproducible run to run even without the cache (4.8208-4.8342); cache runs (4.8224-4.8288) sit inside
that spread.

Not yet done: a long greedy-decode text comparison through llama-server, a server run with mixed batch sizes (watch
re-record hiccups and cache growth), MoE models, GGML_SYCL_PIPELINE, more than 2 cards, other models. The patch is
not published yet.

## Measurement 4: graph cache + per-card launch threads (2026-10-22)

The cache leaves a few ms of launch per forward, and Measurement 2 pointed at launching each card's subgraph from its
own host thread. That used to hang on the Level Zero two-thread launch deadlock
([intel/llvm#23530](https://github.com/intel/llvm/issues/23530)). Setting
`UR_L0_V2_DISABLE_ZE_LAUNCH_KERNEL_WITH_ARGS=1` (read by the Level Zero v2 adapter; it switches kernel launches to the
older set-argument + append-launch path) avoids the hang here: a standalone reproducer went from hanging 6 of 6 runs
to 10 of 10 clean, with no measurable launch-rate cost, and it cost nothing in the llama.cpp runs below.

Per-card threads are a local, env-gated meta-backend change (not published). Same model and settings as before, no
MTP (llama-bench forwards only), tok/s, median of reps 3-8:

| test | layer | tensor + cache | **tensor + cache + per-card threads** | vs layer | vs cache only |
|---|---:|---:|---:|---:|---:|
| pp1 | 17.95 | 24.24 / 24.26 | **25.13 / 25.56** | **+40-42%** | +4-5% |
| pp5 | 84.18 | 110.02 / 109.55 | **113.29 / 114.92** | **+35-37%** | +3-5% |
| pp8 | 131.51 | 171.93 / 172.11 | **177.81 / 179.71** | **+35-37%** | +3-4% |
| pp512 | 980.18 | 1280.8 / 1284.2 | **1285.6 / 1290.7** | **+31-32%** | ~0 |
| tg32 | 17.98 | 23.55 / 23.43 | **24.57 / 25.06** | **+37-39%** | +5-7% |

- The two levers stack, but once subgraphs are replayed there is little launch time left to overlap, so the threads
  add only 3-7% at 1-8 tokens.
- **The graph cache also speeds up prompt batches:** pp512 goes from ~980 (layer) / ~954 (tensor eager) to ~1,285.
- Correctness: perplexity at ub 4 bit-identical (4.8336, all chunks equal; 6.2 s per pass vs 9.4-9.7 eager); ub 512
  4.8282, inside the eager spread.
- Stability: four ~6.5-minute llama-bench loops (`-p 1,5,8,512 -n 128 -r 60`) ran clean; decode tg128 24.8-25.1
  across all four (layer 18.0, +38%). Per-card threads *without* the cache crashed once in four loops inside oneMKL's
  threading DLL (not root-caused), so the threads-only setup is not recommended; with the cache no crash was seen,
  which makes it rare but does not prove it gone.

Still not done for either setup: llama-server with real mixed traffic, MTP end to end, MoE models, more than 2 cards.

## Candidate fixes

| idea | result on this machine (Windows, Level Zero) |
|---|---|
| Two staging slots, drop the upload waits (ordering kept by the next call's download waits) | +1-2%, noise level |
| `host_task` hand-off instead of a blocking wait | **-25%**: a pending host_task routes later launches through the DPC++ scheduler (13 us per node) |
| `ext_oneapi_submit_barrier` on each queue with the peer's download event (proposed by @92es on #30358) | **aborts on the first all-reduce** (0xC0000409, "Abort was called at 3440 line"): here the two devices are in separate SYCL contexts and the barrier rejects the other context's event. Probably fine where both queues share one context (likely on Linux); even then the bound above caps the gain at about layer parity on this machine |
| One SYCL context spanning both devices | not built; capped at layer parity by the bound |
| **Launch each card's subgraph from its own host thread** | hangs on the Level Zero two-thread launch deadlock ([intel/llvm#23530](https://github.com/intel/llvm/issues/23530)) unless `UR_L0_V2_DISABLE_ZE_LAUNCH_KERNEL_WITH_ARGS=1` is set. With it and without the cache: works, but one oneMKL crash in four loops. **With the cache: +3-7% more, best overall** ([Measurement 4](#measurement-4-graph-cache--per-card-launch-threads-2026-10-22)) |
| **SYCL graph replay with a per-subgraph cache** (cuts per-node launch cost) | **+27-37% over layer at 1-8 tokens, ub-4 perplexity bit-identical** ([Measurement 3](#measurement-3-per-subgraph-sycl-graph-cache-2026-10-22)); stock graph mode crashes in the driver |
| Fewer nodes via fusion | not tried |

If you test the barrier approach where it does run, please check correctness with perplexity at ub 4 *and* ub 512
plus a long greedy decode against a stock build (a write-after-read race on reused staging buffers would show up
there, not in a short MTP run), and post your OS, driver, and whether `q0->get_context() == q1->get_context()`.

## How to A/B MTP stably (answer to a question on #30358)

- llama-bench and llama-perplexity have no MTP path. MTP runs in llama-server, llama-cli and
  `examples/speculative-simple` (`--spec-type draft-mtp`).
- MTP decode speed = accepted tokens per verify step x verify steps per second. Tensor split changes the reduction
  order, so logits and acceptance can differ slightly from layer split; a tok/s gap can be acceptance, not speed.
- So measure the two parts separately: the cost side with llama-bench `-p 1,5` as above (stable, reports sd), and
  acceptance with `llama-speculative-simple --spec-type draft-mtp --spec-draft-n-max 4 -f prompt.txt -n 512 --temp 0`
  (deterministic per build and split mode; prints decoded tok/s, n_drafted, n_accept).

## Next steps

- On Windows Level Zero, 2-card tensor-split decode is host-launch-bound. Exchange/bandwidth fixes (#30956, the
  2-buffer patch, barriers) cannot beat layer split at 1-8 tokens here; caching SYCL graphs per subgraph does.
- Graph cache: server test with mixed batch sizes and a long-decode text comparison, then MoE models and 4 cards.
  If those hold, it becomes the recipe for 2-card dense models and an upstream candidate.
- Per-card launch threads stack on the cache for another 3-7% (Measurement 4); worth it only once the oneMKL crash
  seen without the cache is understood.
- Numbers from Linux / single-context setups very welcome, especially the per-forward launch time with and without graphs.
