# Findings — session 11 verification pass (2026-10-27 late)

Written against `work/strata-v41-agent-runner` HEAD `1aecb57`, on GPU-BOX, against
`D:\strata-dsv41-port\build-jit\strata.exe` (44,995,584 B, 19:08:07).

Purpose: verify the session-10 handoff before acting on it. **Two of its load-bearing claims
do not hold.** Do not plan from `HANDOFF-SESSION-10.md` §3/§4 unamended.

-

## 1. HEADLINE — the multi-GPU expert tier is NOT a stub. It is ported and it works.

`HANDOFF-SESSION-10.md` and `QWEN-SPEED.md` both state the second-GPU expert tier is a SYCL
stub, that `--peer-device` is the only multi-GPU entry point, and that `--expert-parallel-device`
"no longer exists in v0.2.7". **All three statements are wrong.**

Measured, not inferred:

- `sycl/src/core/peer_experts.cpp` is 41 lines of deliberate refusal — that part is true.
  But it is not the only multi-GPU path in the tree.
- `sycl/src/core/remote_experts.cpp` is **482 lines of live, ported SYCL** (`RemoteExperts`),
  wired into the engine at `sycl/CMakeLists.txt:200`, with 40 dpct markers and no stub.
- The flags are `--expert-cache-device1|2|3 N|auto`, present in the binary's own `--help`
  (`exe-help2.txt`) and at `sycl/src/program/generate.cpp:922-924`.
- `--expert-parallel-device` was **removed upstream** (0 hits in `generate.cpp`, 0 in
  `exe-help2.txt`). The lab configs in `strata-windows-port/configs/` still pass it, so those
  configs cannot reproduce on v0.2.7 as written. That is a real, separate fact — but it does not
  make `--peer-device` the successor, and it does not mean multi-GPU is unavailable.

### 1a. Measured decode, per tier — FINAL, n=3 per tier

One prompt set (`--tokens "9707,11,1879,13,374,264,1293,13" --max-new 32`), one build, only the
`--expert-cache-device*` flags varied between configs. Scripts `g{1..4}_r{1..3}.cmd`, logs
`g{1..4}_r{1..3}.txt` in `D:\strata-dsv41-port\`.

| Cards | Flag set | Runs | Median | vs 1 card |
|---|---|---|---:|---:|
| 1 | (none) | 10.83 / 11.08 / 11.02 | **11.02** | 1.00x |
| 2 | `--expert-cache-device1 auto` | 29.42 / 28.74 / 27.38 | **28.74** | **2.61x** |
| 3 | `+ device2` | 28.64 / 29.06 / 28.24 | **28.64** | 2.60x |
| 4 | `+ device2 + device3` | 29.70 / 29.85 / 29.48 | **29.70** | 2.69x |

All runs `EXIT=0`. Spreads are tight (±1.1 on 2 cards, ±0.15 on 4), so these are not the bimodal
variance regime W-042 warned about — that was the llama.cpp path.

**Card 2 buys 2.6x. Cards 3 and 4 together buy +3% over card 2.** That is the number that matters
for planning, and it is the exact opposite of the handoff's framing.

At 2 cards: `CUDA1: 13958 additional experts`, and 10,618 + 13,958 = 24,576 = **exactly the full
expert set**, so this is measured with every expert resident on the GPUs.

### 1a-bis. Context scaling (2 cards, plain config, `--max-new 16`)

| Context | Slots GPU0 | CUDA1 experts | Decode |
|---|---:|---:|---:|
| 32k | 10,425 | 14,151 | 27.00 |
| 64k | 10,173 | 14,403 | 23.74 |
| 200k | 9,131 | 15,445 | 22.56 |

All `EXIT=0`. **200k runs fine on this build.** Decode falls ~17% from 32k to 200k as the KV takes
VRAM away from the expert cache.

> Not directly comparable to the 32-token runs above: `--max-new 16` here, so speculative decoding
> had fewer rounds to amortise. Read the trend, not the absolute value.

### 1b. Why cards 3-4 are nearly free of value — the constraint is not matmul

Per-round profile at 32 tokens, from the engine's own instrumentation:

| ms/round | 1 card | 2 cards | 4 cards |
|---|---:|---:|---:|
| decode rate | 10.92 | 27.75 | 29.78 |
| dispatch `run` (GPU expert work) | 9.62 | 5.77 | 3.83 |
| CPU pool call | 15.99 | 15.07 | 17.13 |
| verify window wait-for-rings | 20.00 | 19.97 | 19.81 |
| round time (derived) | ~146 | ~58 | ~54 |

GPU expert work **does** halve when the second card joins (9.62 -> 5.77 ms). Past that it keeps
shrinking (3.83) but the round time does not, because the CPU pool call and the per-layer
wait-for-rings are flat and now dominate. **Both are per-layer host work that does not divide
across cards.**

This directly falsifies `QWEN-SPEED.md` §4b-c. That section reasons "480 expert calls x 21 us =
10.1 ms -> 99 tok/s, so decode is expert-matmul-bound, so four cards divide the 480". The 1-card
measurement already sits at 10.9, not 99; and the 2-card measurement sits at 27.8, not 198. The
480x21us arithmetic is not the binding term on this box at this window size.

### 1c. Consequence for the two-track decision

`QWEN-SPEED.md` §4 predicted 180-220 tok/s on 4 cards and used the missing multi-GPU tier
as the reason Qwen needs `sycl/src/core/` work first. Measured 4-card is **29.78**. The tier
exists; the scaling is what is missing. Those are different problems and the second one is in
the per-layer host path, not in expert placement.

**Do not start QWEN-3 (port the peer tier to SYCL) as scoped.** The prior art named there is
already ported. The real work is the flat CPU-pool and wait-for-rings terms.

-

## 2. The 12.95 tok/s baseline does not reproduce; the real single-card figure is ~11

| Source | Cards | Decode |
|---|---:|---:|
| `bench2.txt` (session 10) | 1 | 12.95 |
| this pass, `ep1c` | 1 | 10.92 |
| this pass, `ep1d` | 1 | 11.08 |

Same binary, same pack, same prompt, same flags. Spread is 12.95 vs 10.9-11.1 (~18%). Per
`FINDINGS.md` W-042 this box is known non-deterministic on single samples, so treat 12.95 as the
top of a range, not the baseline. **Issue #20 is still open and still worth doing** — but the
starting number is ~11, not 12.95, and the 1-card figure must be quoted with n>=3.

-

## 3. Correctness observation (not a claim — flagging it, do not act on it yet)

The 1-card and 2-card runs produce **different continuations** from the same prompt and seed:

- 1 card: `"\n\nAlso include the token ids for a few tokens so we can assert in tests? e.g., id of \"hello\" = 15339"`
- 2 cards: `"\n   Counting: 2 im_start (im_start, im_start), 2 im_end, 1endoftext. Wait,"`

The engine documents this class of divergence (`expert_cache` rounding differs between GPU and
CPU, "same quality, slightly different replies"). The prompt here is non-linguistic token soup,
so this is **weak evidence** either way. It is recorded because a multi-GPU plan that says
"identical answers to the one-card run" (QWEN-3 acceptance) cannot be checked until someone
runs a real prompt. Do not treat this as a regression report.

-

## 4. The lab's 97.6 config was tested and is not the explanation

`strata-windows-port/configs/strata-iq3s-200k1-pf8k.json` carries **83 env vars** plus 36 args
and `--expert-parallel-device 1`. I reconstructed it with the flag remapped to
`--expert-cache-device1..3 auto` and ran it:

| Config | Cards | Context | Decode |
|---|---:|---:|---:|
| plain (this pass) | 4 | 8k | **29.78** |
| lab config, 83 env vars | 4 | 8k | 21.71 |
| lab config | 4 | 200k | **REFUSED**, EXIT=2 |

The lab config is **slower**, not faster. At 200k it refuses:

```
strata generate: REFUSED: 14754 experts are neither in VRAM nor mirrored; with
STRATA_VERIFY_NO_HOST the device plan cannot run them and generation would lack a safe
host fallback - raise STRATA_MIRROR_MIB or the free RAM, or lower --max-context
```

### 4a. CORRECTED — the refusal is the env pair, not the context length

An earlier draft of this file said "200k does not currently run on the port". **That is wrong** and
was over-generalised from one config. The plain config runs 200k at 2 cards, `EXIT=0`, 22.56 tok/s
(§1a-bis).

The refusal is specifically the lab config's `STRATA_VERIFY_NO_HOST=1` combined with
`STRATA_MIRROR_MIB=0`: no host fallback, and the mirror explicitly zeroed. Filed as issue **#22**.

So the correct statement is narrow: **the published 200k lab config is internally unsatisfiable at
its own context length on this box, but the context length itself is fine.**

Caveat that still stands: the lab config was written for `--expert-parallel-device`, whose semantics
differ from `--expert-cache-device*`. A remapped config is not the lab's config. Treat 21.71 as "the
env sweep does not close the gap", not as a measurement of the lab setup.

-

## 5. Repo state (small, but the handoff said "pushed" without qualification)

- Branch and origin agree: `git rev-list --left-right --count` = `0 0` at `1aecb57`. Commits are pushed.
- **Working tree is dirty**: `machine-manifest.json` modified (65+/48-), plus 5 untracked `*.bak-*`.
  The committed `machine-manifest.json` still carries the old `"PARTIAL / AMBIGUOUS"` PCIe block;
  the measured ~12 GB/s version exists only in the working tree. Anyone reading the repo gets the
  stale PCIe record.
- `HANDOFF-SESSION-10.md` §1 says "Last commit at handoff: `d956c22`" while the file itself landed
  in `1aecb57`. Cosmetic, but it misleads the next session's verification step.

-

## 6. What I did not do

- Did not touch `sycl/src/dsv41/` (still absent — that part of the handoff is correct).
- Did not start dsv41 STEP-003. No gate moved.
- Did not modify production llama-swap. GPU-BOX verified idle (0 `strata.exe`, 0 watchers) before
  and after; the one python PID is `xpu_power_exporter.py`, unrelated.
- Did not run the 7-prompt `sbench.py` set. All numbers here are single-prompt, `--max-new 32`.

-

## 7. Actions taken (session 11, same day)

All five of the originally-recommended items were completed:

1. **`QWEN-SPEED.md` corrected.** §4 replaced with measured data; the 180-220 prediction is gone and
   labelled as retracted. §3's "why it is 7.5x slower" corrected in place with the old text kept for
   the record. §5 QWEN-2 marked answered, QWEN-3 **refiled** from "port the tier" to "attack the
   flat per-layer host terms". §6's dsv41 dependency claim withdrawn.
2. **`HANDOFF-SESSION-10.md` corrected.** Banner at the top, plus inline **[S11 CORRECTED]** markers
   on #20, #21, Track A and Track B.
3. **Issue #21** retitled and commented — premise retracted, measured grid posted, impact on STEP-004
   removed. **Issue #20** commented with the n=3 baseline and the remaining open items.
4. **Issue #22 filed** — the 200k refusal, correctly scoped to the env pair rather than to context.
5. **`machine-manifest.json`** — the measured ~12 GB/s PCIe block committed, with the old PnP
   "link width = 1" reading retained as an explicitly superseded record rather than deleted.

### Still open

- QWEN-3 as refiled (host terms) — not started.
- #20's prefill measurement, `--spec 0` control, and the 7-prompt set — not done.
- dsv41 STEP-003 — untouched, as instructed.

-

## 8. Honest limits of this pass

- The grid in §1a is **n=3 per tier**, which is enough to see that 3-4 cards are flat, not enough to
  claim the third digit. Treat 28.6 vs 28.7 vs 29.7 as "the same".
- One prompt, one seed, `--max-new 32`, 8k context for the tier grid. Nothing here speaks to prefill
  at length.
- The context sweep (§1a-bis) used `--max-new 16`, so it is not directly comparable to the tier grid.
- All runs used `--stream-experts`, so "residency" means the VRAM cache tier, not a host arena.
  A non-streaming setup may order the tiers differently.
- **Process note:** I lost time to two self-inflicted errors worth recording. (a) A detached
  `nohup` loop was started over ssh and its parent died, silently killing the run — use `setsid`
  or foreground. (b) I generated configs with an off-by-one in the tier-to-flags mapping and
  briefly mislabelled 1/2/4-card scripts. The measurements above come from the corrected `g*`
  scripts, verified by their own `CUDA1/2/3: N additional experts` log lines.

-

## 9. Speculation depth sweep (added same evening, prompt told me to test 2 and 3)

All earlier numbers in this file used `--spec 4`. This section varies depth on **realistic prompts**
instead of the token-ID soup used above.

### 9a. `--spec 0` is impossible on this pack

```
strata generate: D:\AI\Strata-data\packs\iq3_s is a native (IQ) pack:
it needs --native SHARD1, --spec T (T >= 2) and --prefill CHUNK
EXIT=2
```

So there is **no non-speculative baseline** available on IQ3_S. Any decode figure from this pack is
speculation-assisted. The lab's 97.6 was too.

### 9b. Measured, 2 cards, `--max-new 64`

Prompts: prose (33 tokens), code (26 tokens). Both `--spec-min-p 0`, MTP drafter, int8 KV, 8k context.

| Prompt | Spec | tok/s | Accept | tok/round | Round ms |
|---|---:|---:|---:|---:|---:|
| prose | 2 | 34.27 | 0.561 | 1.55 | 45.2 |
| prose | 3 | **37.92** | 0.426 | 1.83 | 48.3 |
| prose | 4 | 32.58 | 0.276 | 1.81 | 55.6 |
| prose | 8 | 22.70 | 0.127 | 1.86 | 81.9 |
| code | 2 | 43.30 | 0.811 | 1.86 | 43.0 |
| code | 3 | 47.98 | 0.750 | 2.44 | 50.9 |
| code | 4 | **53.16** | 0.656 | 2.83 | 53.2 |
| code | 8 | 47.40 | 0.429 | 3.82 | 80.6 |

**Prose prefers depth 3, code prefers depth 4.** Depth 8 is a regression on both: round time nearly
doubles (45 -> 82 ms) while tokens/round barely moves (1.55 -> 1.86).

Best measured: **53.16 tok/s** (code, spec 4) vs 28.74 on the soup prompt at spec 4.

### 9c. The important comparison: round time is NOT the gap

| | ms/round |
|---|---:|
| Our best (code, spec 4) | **53.2** |
| Lab 97.6 implies, at 5.0 tok/round | 51.2 |
| Lab 97.6 implies, at 5.5 tok/round | 56.4 |

**We are already at the lab's per-round cost.** Their 97.6 came from extracting ~5.5 accepted tokens
per round against our 2.83. Holding our 53.2 ms round fixed:

```
2.83 tok/round -> 53.2 tok/s   (measured)
4.00 tok/round -> 75.1
5.00 tok/round -> 93.9   <- the "90ish"
6.00 tok/round -> 112.7
```

**Conclusion: the remaining gap is drafter quality, not the port.** Same round, fewer tokens out of it.

### 9d. Caveats

- **Not comparable to §1a's grid.** Different prompts (33/26 tokens vs 8), `--max-new 64` vs 32.
  Read the spec-depth trend and §9c; do not put 53.16 beside 28.74 as a clean delta.
- The earlier 0.228 acceptance was **substantially my prompt's fault** — a non-linguistic token-ID
  soup is worst case for a draft model. Real prose 0.56, real code 0.81.
- Single sample per cell. The trend is monotone and large enough to trust; individual digits are not.
- `--suffix-draft` and `--lookup-chain` reported **zero windows** in every run. Untested as levers.

### 9e. Next lever

Not spec depth — that is tuned. The drafter (`D:\AI\Strata-data\mtp\rt`) is the constraint. Options:
a larger draft head for this model, or `--lookup-chain` / `--suffix-draft` which have never actually
engaged here.
