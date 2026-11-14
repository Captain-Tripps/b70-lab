# Prompt read: 1536-token chunks with 64k checkpoint spacing - 2026-11-13

## Decision

Promoted at Jon's request after a clean 30-minute soak. The live GLM entry now reads prompts in 1536-token chunks
(`--prefill 1536`, was 768) with a checkpoint every 65536 tokens (`STRATA_GLM_CKPT_EVERY=65536`, was the 16384
default). A cold 45.8k read goes from 42.0 to 32.4 s and a cold 115k read from 103.7 to 82.2 s (both about -21%, same
session control). Decode is unchanged. The two changes stack: each one alone gave about half of that.

1536 does change the numbers. The logits at 32k agree on the top token at 62 of 64 positions, the same size of
shift that kept `STRATA_GLM_PREFILL_SUB=768` out on 2026-11-10. What this record adds is a quality check against the
real next tokens: 1536 scores the same as 768 (mean log-loss 0.988 vs 0.985 on 63 tokens of the 32k input, 53 vs 52
of them predicted). Within what 63 tokens can show, that is no measurable loss.

Rollback: set `--prefill 768` and remove `STRATA_GLM_CKPT_EVERY` from the GLM engine config (a backup of the old
config sits next to it on the lab host).

## Why 1536 is faster

The grouped XMX expert kernel dequantizes weights per 32-row tile. At 768-token chunks the routed experts get few
rows each and the tiles run about 53% full; doubling the chunk fills them. The gain comes from that, not from PCIe:
no arm copied experts in while a prompt ran (`*-staging.json`, all zero).

## Chunk screen

Same setup as the [checkpoint-spacing screen](../2026-11-13-prefill-ckpt-screen/): live executable, live config and
server tree on a separate port, one fresh process per arm, an 8.9k warm-up, a cold 45,818-token read, a cold
115,108-token read and two 512-token decodes. [`screen_chunk.py`](screen_chunk.py), [`all_chunk.py`](all_chunk.py).

| Arm | Cold 45.8k | Cold 115.1k | Card 0 VRAM free |
|---|---:|---:|---:|
| 768 (live), opening control | 40.3 s | 101.3 s | |
| 1024 | 37.5 s | 93.2 s | |
| 1536 | 35.9 s | 86.9 s | 1.1 GB |
| 2048 | 36.0 s | 86.1 s | 0.5 GB |
| 768 (live), closing control | 41.9 s | 105.4 s | |

The controls drift ~4% over the run. 2048 adds nothing over 1536 and leaves half a gigabyte free on card 0, so 1536
was the one carried forward.

## Combined arm

Same script, `ckpt` and `chunk` set together. [`all_kl.py`](all_kl.py) runs it after the logit check.

| Arm | Cold 45.8k | Cold 115.1k | Decode 1 / 2 |
|---|---:|---:|---:|
| 768, 16k spacing (live then), rerun | 42.0 s | 103.7 s | 43.8 / 45.2 tok/s |
| 768, 64k spacing | 38.6 s | 98.6 s | 43.8 / 45.2 |
| **1536, 64k spacing** | **32.4 s** | **82.2 s** | 43.6 / 45.0 |

The first attempt at the 768 control (`q768-live`) ended in the known `ze_intel_gpu64.dll` access violation 66k
tokens into the 115k read; `q768-live-r2` is the rerun.

## Logit check

Teacher-forced dumps, the method of the [2026-11-10 sub-batch check](../2026-11-10-sub768-validation/): the isolated
`generate.exe` with `STRATA_GLM_KL_DUMP=<file>,64` and speculation off reads all but the last 64 tokens of an input,
then forces those 64 one at a time and writes each position's full-vocabulary logits. The forced steps run the
decode path, so any difference comes from the KV cache the prompt read wrote. Inputs: the 8k code and records inputs
from 2026-11-10 and the 32k long input. Arms 768, 1536, 768 again. [`kl_chunk.ps1`](kl_chunk.ps1),
[`cmp_kl.py`](cmp_kl.py), [`nll_kl.py`](nll_kl.py).

| Input | 768 vs 768 | 768 vs 1536 top-1 | Mean KL | Max KL |
|---|---|---:|---:|---:|
| code 8k | bit-identical | 64/64 | 0.000006 | 0.000077 |
| records 8k | bit-identical | 64/64 | <0.000001 | 0.000015 |
| long 32k | bit-identical | 62/64 (rows 49, 51) | 0.0129 | 0.110 |

[Comparison](kl-comparison.txt). The large raw logit gaps in it (up to 12) sit on vocabulary entries with almost no
probability, which is why KL stays small.

Why 1536 cannot match 768 exactly: at 1536 the mixer sub-batch goes from 512 to 1024 on its own, and the shared expert
sub-batch (2048, capped at the chunk) goes from 768 to 1536. `STRATA_GLM_PREFILL_SUB` sets both at once, so no
setting keeps 1536's speed with 768's numbers.

Log-loss of the real next token on the 63 scorable rows ([`true-token-loss.txt`](true-token-loss.txt)):

| Input | 768 | 1536 |
|---|---:|---:|
| code 8k | 0.0001, 63/63 | 0.0001, 63/63 |
| records 8k | 0.0000, 63/63 | 0.0000, 63/63 |
| long 32k | 0.9852, 52/63 | 0.9877, 53/63 |

The 8k inputs are easy for both. On 32k the difference is 0.0025 in mean log-loss, one row of noise either way.

## Soak

The [2026-11-13 buffer-reuse soak](../2026-11-13-slot-buffer-reuse/#soak) mix, 30 minutes on the live build with
`--prefill 1536` and `STRATA_GLM_CKPT_EVERY=65536`. [`soak_1536.py`](soak_1536.py),
[`soak-requests.jsonl`](soak-requests.jsonl).

| Request | 768 / 16k soak (median) | 1536 / 64k soak (median) |
|---|---:|---:|
| 115k first read | 103.2 s | 82.8 s |
| 31k conversation switch | 28.3 s | 22.5 s |
| Repeated 115k edits | 0.56 s | 0.51 s |
| Return to the long conversation | 0.56 s | 0.52 s |
| Short switch | 0.33 s | 0.31 s |

57 cycles, 469 requests, no errors and no driver crash. Every request type gave one answer across all cycles, and
every answer ran its full 64 tokens. The answers differ from the 768 soak's, as the logit shift predicts. The
soak does not keep the answer text; the screen arms' answers read correctly, as did the live smoke after
promotion. Lowest free RAM 75.3 GiB.

## After promotion

Through the proxy, cold 45.8k read: 34.9 s (1,379 tok/s), correct one-line summary. A short arithmetic prompt
answered correctly. The engine log shows chunks of 1536 and the 64k spacing.

## Driver crash count

The access violation hit 2 of 6 runs at 768 and 0 of 4 at 1536 in this round (plus the soak, clean). Too few runs to
say the chunk size affects it.

## Setup

4x Arc Pro B70, Windows 11, driver 32.0.101.9175, live executable `de2540a6...`, layer split 14,25,36. GLM unloaded
from the proxy after a quiet check, with Jon's OK, for the screens and the soak. Evening of 2026-11-13. Set
`MAYA_WORK` to the engine checkout and `PROXY_URL` to the proxy before running the scripts; the input token files and
the 38 MB logit dumps stay on the lab host.
