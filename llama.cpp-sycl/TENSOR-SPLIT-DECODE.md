# Why 2-card `-sm tensor` decodes slower than `-sm layer` on SYCL (working notes)

Living page, started 2026-10-22. Collaboration welcome: open an issue or a discussion in this repo with numbers
from your own cards. Upstream context: [ggml-org/llama.cpp#30956](https://github.com/ggml-org/llama.cpp/pull/30956)
(faster exchange, by @92es) and the thread on [#30358](https://github.com/ggml-org/llama.cpp/pull/30358).

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

## Candidate fixes

| idea | result on this machine (Windows, Level Zero) |
|---|---|
| Two staging slots, drop the upload waits (ordering kept by the next call's download waits) | +1-2%, noise level |
| `host_task` hand-off instead of a blocking wait | **-25%**: a pending host_task routes later launches through the DPC++ scheduler (13 us per node) |
| `ext_oneapi_submit_barrier` on each queue with the peer's download event (proposed by @92es on #30358) | **aborts on the first all-reduce** (0xC0000409, "Abort was called at 3440 line"): here the two devices are in separate SYCL contexts and the barrier rejects the other context's event. Probably fine where both queues share one context (likely on Linux); even then the bound above caps the gain at about layer parity on this machine |
| One SYCL context spanning both devices | not built; capped at layer parity by the bound |
| **Launch each card's subgraph from its own host thread** (the lever the numbers point to) | **hangs** after a few all-reduces: the known Level Zero two-thread launch deadlock ([intel/llvm#23530](https://github.com/intel/llvm/issues/23530)), still present on driver 32.0.101.8976. Rough ceiling if it worked: launch 41.5 -> ~21 ms, pp1 ~20-23 tok/s (estimate) |
| SYCL graph replay per subgraph (cuts per-node launch cost) | graph mode currently exits/crashes; would also need up to 128 cached executable graphs per card |
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

- On Windows Level Zero, 2-card tensor-split decode is host-launch-bound; exchange/bandwidth fixes (#30956, the
  2-buffer patch, barriers) cannot beat layer split at 1-8 tokens here. Layer split stays the choice for decode.
- Unblockers worth watching: a driver fix for the two-thread launch deadlock (then per-card launch threads), and working
  SYCL graph replay.
- Numbers from Linux / single-context setups very welcome, especially the per-forward launch time.
