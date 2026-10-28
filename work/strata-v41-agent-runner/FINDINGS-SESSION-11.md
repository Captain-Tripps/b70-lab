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

### 1a. Measured decode, per tier

One prompt set (`--tokens "9707,11,1879,13,374,264,1293,13" --max-new 32`), one build,
only the `--expert-cache-device*` flags varied. Logs: `ep1c/ep1d` (1 card), `ep2b/ep2d/ep2_clean`
(2), `ep3_clean` (3), `ep4`/`clean3` (4).

| Cards | Devices in use | Decode tok/s (per run) | n |
|---|---:|---|---:|
| 1 | GPU0 only | 10.92, 11.08 | 2 |
| 2 | + CUDA1 13,958 experts | 27.75, 27.39, 29.33, 29.39 | 4 |
| 3 | + CUDA2 6,979 | 28.26 | 1 |
| 4 | + CUDA3 4,653 | 29.78 | 1 |

**Card 2 buys 2.5x. Cards 3 and 4 buy +7% together.** That is the number that matters for
planning, and it is the exact opposite of the handoff's framing.

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

The lab config is **slower**, not faster. Its 200k setting refuses outright on this build:

```
strata generate: REFUSED: 14754 experts are neither in VRAM nor mirrored; with
STRATA_VERIFY_NO_HOST the device plan cannot run them and generation would lack a safe
host fallback - raise STRATA_MIRROR_MIB or the free RAM, or lower --max-context
```

So 97.6 is not explained by the env sweep, and the 200k configuration **does not currently run
at all** on the v0.2.7 port. That is a genuine blocker for the headline lab result and should be
its own issue.

Caveat on this section: the lab config was also written for `--expert-parallel-device`, whose
semantics differ from `--expert-cache-device*`. A remapped config is not the lab's config. Treat
21.71 as "the env sweep does not close the gap", not as a measurement of the lab setup.

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

## 7. Recommended next actions

1. **Correct `QWEN-SPEED.md` §4 and `HANDOFF-SESSION-10.md` §3-4 before they are used to plan.**
   The 4-card prediction (180-220) and the "tier is a stub" premise are both contradicted by
   measurement. This is the highest-value edit in the repo right now.
2. **Refile QWEN-3** from "port the multi-GPU tier" to "reduce the flat per-layer host terms"
   (CPU pool ~15-17 ms/round, wait-for-rings ~20 ms/round). That is where 29.78 is being spent.
3. **New issue: the 200k lab config refuses on v0.2.7** (section 4). Either the mirror budget
   or `STRATA_MIRROR_MIB` handling changed, and nothing in the port is currently validated at
   the context length the 97.6 headline was measured at.
4. **#20 remains valid** but restate the target: ~11 tok/s single-card with n>=3, not 12.95.
5. **Commit the machine-manifest PCIe block** or revert it — a repo that records "ambiguous"
   while the working tree holds measured 12 GB/s will mislead the next reader.

-

## 8. Honest limits of this pass

- 3- and 4-card figures are **n=1** each. Direction is unambiguous (they are flat), exact values
  are not. Redo with n>=3 before quoting.
- One prompt, one seed, `--max-new 32`, 8k context. Nothing here speaks to prefill at length or
  to the 200k regime.
- All runs used `--stream-experts`, so "residency" means the VRAM cache tier, not a host arena.
  A non-streaming setup may order the tiers differently.
