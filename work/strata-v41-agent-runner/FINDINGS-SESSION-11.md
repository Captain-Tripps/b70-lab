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

-

## 10. Lever sweep (prompt supplied an external tuning table; tested each against the binary)

### 10a. Most of the supplied table does not apply to Strata

The external table is llama.cpp / llama-swap vocabulary. Verified each against the binary, which
errors loudly on unknown flags (`unknown argument: --bogus-flag-xyz`):

| Supplied param | In Strata? | Finding |
|---|---|---|
| `--vram-reserve-mib` | **yes** | Already passed at 1024 in every run. Tested 2048 below. |
| `--vram-reserve-later-mib` | **yes, but N/A** | Parsed (`generate.cpp:1924`), but only used as `later &&` in the layer-split stage sizing (`:3685`). We use the expert-cache tier (`--expert-cache-device*`), not `--layer-split`, so it never applies. |
| `--kv-cache-precision` | **no** | `unknown argument`. Strata spells it `--kv int8\|fp16\|q4_0\|k8v4`. We already use int8. |
| `--parallel` | **no** | `unknown argument`. That is a llama-server concept; Strata has `--batch` slots and the help explicitly warns slot batching costs VRAM per slot. |
| `gpu` / `gpu_order` | **no** | Not flags at all — llama-swap config keys. Strata selects devices by `--expert-cache-device1\|2\|3` and `--layer-split`. |

So of five suggested levers, **one was already in use and one is inapplicable by design**. The other
three are for a different engine. This is worth recording: that table should not be applied to Strata
without translation.

### 10b. Nine variants, code prompt, `--spec 4`, 2 cards, `--max-new 64`

| Variant | Flags | tok/s | Accept | tok/round | Round ms |
|---|---|---:|---:|---:|---:|
| base | (none) | **53.02** | 42 of 64 (0.656) | 2.83 | 53.4 |
| sd0 | `--suffix-draft 0` | **54.92** | 43 of 63 (0.683) | 2.83 | 51.5 |
| sd8 | `--suffix-draft 8` | 53.80 | 43 of 63 (0.683) | 2.83 | 52.6 |
| kvg | `--kv-grow` | 52.88 | 42 of 64 (0.656) | 2.83 | 53.5 |
| lk2 | `--lookup-chain 2` | 52.47 | 41 of 71 (0.577) | 1.86 | 35.4* |
| hnstr | `--mtp-hnorm stream` | 52.29 | 42 of 65 (0.646) | 2.83 | 54.1 |
| lk4 | `--lookup-chain 4` | 51.38 | 41 of 71 (0.577) | 1.86 | 36.2* |
| vr2k | `--vram-reserve-mib 2048` | 47.24 | 41 of 66 (0.621) | 2.83 | 59.9 |
| mtpq4 | `--mtp-q4 all` | **18.09** | **0 of 189 (0.000)** | 1.00 | 55.3 |

\* The lk2/lk4 round-time figure is anomalously low against a nearly identical tok/round. Do not build
on it; the tok/s number is the reliable one.

**Nothing beats baseline beyond noise.** `sd0` leads by 3.6%, which is inside single-sample spread on
this box. Baseline itself reproduced at 53.02 vs 53.16 earlier, so ±0.3% run-to-run is normal — 3.6%
is not clearly outside it.

### 10c. Two real findings

**`--vram-reserve-mib 2048` is a 10.9% regression.** Not neutral: at 2048 the expert cache drops from
10,618 to 10,091 slots and CUDA1 takes 527 more experts (14,485 vs 13,958). Round time rises 53.4 ->
59.9 ms. On this box the 1024 default is correct, and the external table's "1024 to 2048" advice is
wrong for it — more reserve means more experts pulled over the host path.

**`--mtp-q4 all` is broken, not slow.** 0 of 189 drafts accepted across 64 rounds, every round
exactly 1 token. The 4-bit draft head produces drafts that never match. Worth reporting upstream.

### 10d. Unintended gift: the non-speculative baseline

`--spec 0` is refused on native IQ packs, so I said earlier there was no non-spec baseline. `mtpq4`
accidentally provided one: with the drafter producing garbage, every round degenerated to exactly
1 token — i.e. plain decode.

| | tok/s | tok/round | round ms |
|---|---:|---:|---:|
| plain decode (mtpq4, 0 accepted) | 18.09 | 1.00 | 55.3 |
| spec 4 (base) | 53.02 | 2.83 | 53.4 |

**Round cost is essentially identical (55.3 vs 53.4 ms).** Speculation is worth **2.93x**, and it is
worth it entirely through tokens-per-round, not through cheaper rounds. This is the cleanest
confirmation yet of §9c: the engine is round-cost-bound, and the only lever that matters is how many
tokens a round produces.

### 10e. Correction to an earlier claim

I wrote in §9d that `--suffix-draft` reported zero windows in every run. That was true of the
token-soup prompt only. On the code prompt, base and sd8 both show `2 windows, drafts accepted 4 of 4`
while sd0 shows `0 windows`. So suffix drafting does engage on realistic text — it is just worth ~2
tokens out of 64, which is why `sd0` and `sd8` are indistinguishable.

### 10f. Where this leaves the gap

Best measured on this box: **54.92 tok/s** (sd0) vs the lab's 97.6. Acceptance is 0.683 against their
implied ~0.9, and tokens/round is 2.83 against their implied ~5.5, at the same per-round cost.

Raising spec depth does not help (prose peaks at 3, code at 4, depth 8 regresses). Every engine-side
flag tried here is neutral or worse. **The remaining gap is the draft model's quality.** A better MTP
head is the only lever left that the measurements point to — nothing in the flag surface moves it.
