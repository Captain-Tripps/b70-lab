# GLM-5.3 Hill-Climb Log — 2026-10-21

First valid campaign after the environment correction (see [ROADMAP.md](./ROADMAP.md) "Environment correction").
All arms on the degraded host (96 GB visible, WHEA Id 22 every boot, one CPU socket memory path under repair).

## Standing rules this campaign

- Every arm: `GGML_SYCL_IDLE_HEARTBEAT_SEC=30` + 300 s zero-request idle soak before any bench.
- `squal.py` 4/4 before a single speed number is recorded.
- `sbench.py --n 512 --rounds 2 --long 30000` from Windows against the arm's loopback port.
- Runtime fingerprinted per arm (dir name is decorative: g10 dir = build 251 commit `4cc67bb7f`).
- One variable vs the B0 baseline per arm. Preflight idle manifest captured before each launch.

## Arms

All arms: g10 runtime, Maya-M IQ2_S, `-c 131072 -ts 26.3,23.8,22.8,27.1 -b 2048 -ub 512 -fa on`,
DIO, MTP `draft-mtp` (unless noted), blk.44 experts on CPU, heartbeat 30.
Log dir on GPU-BOX: `%USERPROFILE%\AI\logs\arms\<tag>.*`.

| tag | variable | mean decode (r2+) | after 31k prompt | prompt tok/s | squal | soak | VRAM total / max card | verdict |
|---|---|---|---|---|---|---|---|---|
| `b0-g10-128k-hb30` | baseline, 128k | **25.0** | 15.4 | 214 | 4/4 | 0.5 s | 114.58 / 28.93 | baseline |
| `b1-g10-128k-q8kv` | `--cache-type-k/-v q8_0` | 24.9 | 15.5 | 213 | 4/4 | 0.5 s | 114.12 / 28.84 | wash: MLA latent KV already compact; q8 buys 0.5 GB, no speed move. Safe but pointless. |
| `b2-g10-128k-mtpn6` | `--spec-draft-n-max 6` | 25.1 | 14.9 | 213 | 4/4 | 0.5 s | 114.86 / 28.99 | wash: acceptance saturates at n4; n6 pays draft cost it never recovers. Keep n4. |
| `b3-g10-128k-t32` | `-t 16 -> 32` | **25.4** | 14.7 | 213 | 4/4 | 0.5 s | 114.58 / 28.93 | +1.6%, at the edge of the +-1% noise band; not a winner. CPU experts are not the serialization. |
| `b4-g10-128k-queue8` | `GGML_SYCL_PIPELINE_MAX_QUEUED 4 -> 8` | 24.7 | 15.3 | 211 | 4/4 | 0.5 s | 114.58 / 28.93 | wash-to-loss. Keep queue 4. |
| `b5-g10-128k-ub768` | `-ub 512 -> 768` | **25.4** | **17.3** | **234** | 4/4 | 0.5 s | 115.66 / 29.42 | **winner.** 31k prompt 145.9s -> 132.5s; deep decode +12%, first signal outside noise all night. No spill: ub costs only ~0.5 GB/card per 256 ub step. |
| `b6-g10-128k-ub1024` | `-ub 512 -> 1024` | 24.8 | 14.7 | **259** | 4/4 | 0.5 s | 116.86 / 29.98 | **prompt winner.** 31k ttft 120.1 s (+21% prompt rate). Peak card *during bench* 30.22 - 1.85 GB spare, no spill. "ub 1024 spills" folklore disproved on build 251 with this -ts. |
| `b0r-g10-128k-hb30` | B0 repeat (A/B/B/A close) | 25.1 | 15.6 | 212 | 4/4 | 0.5 s | 114.58 / 28.93 | close: +0.4% mean, -1% prompt vs B0 open. No drift all campaign. |

## Campaign summary (A/B/B/A closed)

- **Decode tok/s is flat at 25.0 +- 0.3** across every knob tried: KV quant, MTP depth, CPU threads,
  pipeline queue depth, and ub. It is a property of the runtime+model+card set, not of these switches.
- **Prompt tok/s is NOT flat**: 213-214 is a hard plateau at ub 512 (five arms agree within 1 token/s),
  234 at ub 768, **259 at ub 1024** - a +21% prompt-rate win with zero decode cost and zero quality cost
  (squal 4/4 on all eight runs including the two baseline repeats).
- The old production comment "-ub 1024 does NOT fit (card spills, prompts 20x slower)" is **folklore**:
  at -ts 26.3,23.8,22.8,27.1 on build 251, ub 1024 loads at 29.98 GB max card and peaks at 30.22 GB
  *during a 31k prompt* - still 1.85 GB under the per-card cliff. ub costs ~0.5 GB/card per 256 step.
  The folklore probably predates this -ts allocation or an older FA path; treat config comments as
  hypotheses, not measurements.
- Deep-decode-after-long-prompt (single sample) has +-5% run-to-run variance: the 14.7-15.6 band across
  seven arms means B5's 17.3 was one lucky draw, not a ub effect. Do not chase single-sample wins.
- Heartbeat held all seven arms: 300 s zero-request soak -> answer in 0.5 s, VRAM dead flat, every time.
  The demotion fix is validated at campaign scale.

## Production recommendation (pending operator approval)

Change the live GLM entry `-ub 512` -> `-ub 1024`. Expected on this degraded host: 31k-prompt latency
146 s -> 120 s (-18%), short-reply ttft unchanged, decode unchanged at ~25 tok/s. Watch item: peak card 30.22 GB,
keep >=1.5 GB headroom; if any future change (bigger -c, extra offload) eats it, fall back to 768
(+9%, peak 29.4). Apply via the same hot-reload path (edit + `--watch-config` picks it up, no restart),
and update the stale comment block in the config at the same time.

## What the plateau says

Three independent knobs (KV quant, MTP depth, and note prompt tok/s pinned at 213-214 across all three)
land inside noise of 25.0. Decode is not sitting on a bandwidth cliff: MoE with routing moves only a few GB
per token across ~2 TB/s of aggregate GDDR - the machine is somewhere between ~10% and ~20% of theoretical
weight-read rate. That points at **serialization latency** (per-layer MoE dispatch across 4 cards, the
CPU-offloaded layer-44 experts, MTP verify round-trips), not throughput. Hence the next arms aim at pipelining
and CPU-side parallelism, not bigger/faster weights:

1. `-t 32` (B3): the CPU expert GEMMs for blk.44 run on an EPYC 7402P (24c/48t) with only 16 threads claimed.
2. `GGML_SYCL_PIPELINE_MAX_QUEUED 4 -> 8` (B4): deepen the fork's cross-card submission pipeline.
3. End the session by re-running B0 (A/B/B/A close) to check for drift or thermal/memory-path effects.

## Production action taken this session (operator-approved)

- `C:\llama-swap\config.windows.yaml`: added `GGML_SYCL_IDLE_HEARTBEAT_SEC=30` to the GLM entry (was the only
  one of 21 without it). Backup: `config.windows.yaml.bak-20261021`. Applied **without restart**:
  llama-swap runs `--watch-config` (poll 2 s); log confirmed `configuration reloaded`. The model picks the
  heartbeat up on its next load.

## Windows/WSL interop gotchas hit again (they never miss)

- Two `cmd.exe /c` launches back-to-back inside one bash-over-ssh script: the second silently never runs
  (its redirect file absent). One interop command per ssh call, or verify and retry.
- `arm.ps1` writes `<tag>.ledger.csv` / `<tag>.record.md` / `<tag>.pids.txt` flat in the log dir; do not
  construct `probe.csv`-style paths from B0 folklore.
- `kill-arm.ps1 -Tag <tag>` used to deliberately leave the arm's `llama-server` running (production-safe);
  teardown required a second, fragile `kill-port-server.ps1 -PortPattern <port>` step. Fixed same evening,
  see below - teardown is now one command.

## Same-evening follow-up: atomic arm teardown (TDD)

The two-step teardown (`kill-arm.ps1` then `kill-port-server.ps1`) was the last fragile part of the arm
procedure. Now:

- `arm.ps1` records the arm's own server in `pids.txt` (`server=<pid>`, `port=<port>`), discovered via
  `Get-ArmServerProcess` (`bench/find-arm-server.ps1`): command line must carry the arm's `--port` **and**
  the executable must live under the arm's runtime dir, so a production llama-swap server can never be
  recorded as ours even under a port collision.
- `kill-arm.ps1` stops that server only after re-verifying the recorded PID is still `llama-server.exe`
  (PID-reuse guard) and still on the arm's port (recycled/rebound guard). Unrecorded servers - production,
  or arms from the old file format - are reported and left alone.
- Regression suite: `bench/test-arm-teardown.ps1`, 7 cases, written failing first against a compiled mock
  server (csc.exe; renamed ping.exe and powershell.exe both die as mocks - logged in bench/README.md).
  7/7 green; all four scripts parse clean; deployed to GPU-BOX md5-exact; `-DryRun` smoke on GPU-BOX green
  (build 251, commit 4cc67bb7f; box verified idle-clean, 81.5 GB free, all adapters ~0 GB).

## Late follow-up: arm self-teardown (HANDOFF next step 1, TDD)

`arm.ps1` now frees the GPUs itself. Order is fixed: `record.md` first, then (ready arms only) a warm hold of
`-TeardownHoldMin` (default 90 min; `<tag>.benchdone` releases it within ~15 s), then it stops its own child,
watchdog and recorded server with the kill-arm guards and removes its lock. `-NoAutoTeardown` keeps the old
stay-up behaviour for `kill-arm.ps1`. Built on an uncommitted first draft from another agent; writing the e2e
tests against the real `arm.ps1` surfaced four pre-existing bugs, each now pinned by a case:

- **`server=` was always empty.** `arm.ps1` read `.Id` off the CIM object `Get-ArmServerProcess` returns (it
  only has `.ProcessId`). Every arm since the atomic-teardown patch recorded `server=` with no PID, so
  `kill-arm.ps1` never stopped an arm server - the 7 kill-arm cases fed it hand-written pids files and could not
  see this. (case10a)
- **The watchdog targeted the biggest llama-server on the box**, not the arm's. A production server that loaded
  mid-arm with a bigger working set would have been the one killed. It is now limited to servers under the
  arm's runtime dir; `$alive` likewise means the arm's own server. (case13b)
- **Watchdog kills were invisible in the record**; `record.md` now carries a `watchdog events:` line. (case13a)
- **A stale `<tag>.benchdone`** from an earlier same-tag run would have ended a new hold instantly; it is
  removed at start. (case12a)

Also found: piping `arm.ps1`'s output hangs whenever the arm stays up, because `Start-Process -Redirect*`
inherits the caller's stdout into the child and its llama-server (the first suite run hung at case10 for this
reason; the draft's watcher redirect made it worse and is reverted). The suite now captures arm output through
files; bench/README.md lists it under gotchas.

Result: `bench/test-arm-teardown.ps1` 17/17 green locally (314 s), zero leftover processes. Red run first
against the draft: 10a, 10b, 12a, 13a, 13b failed as expected (plus three test-harness bugs fixed: missing
`tt8.args`, cases 3-4 stand-ins blocking preflight, empty `ExitCode` from `Start-Process -PassThru`).
md5: `arm.ps1` `f55faebf1e169174701f3a929522d6da`, `test-arm-teardown.ps1` `7e35a61434409f293fc0a8fb79131f99`;
`kill-arm.ps1` and `find-arm-server.ps1` unchanged. Deployed to the bench box md5-exact (old `arm.ps1` kept
as `arm.ps1.bak-20261021`); `-DryRun` smoke on the B0 args green (build 251, 81 GB free, adapters ~0 GB,
"auto-teardown ON ... hold 90 min"). No GPU arm has run on it yet - the first real arm is the live check.
