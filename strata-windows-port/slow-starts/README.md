# Strata on Windows: the slow-start lottery (cause: the file cache)

The served Strata build (Qwen3.8-Flash-Next GSQ-RCO IQ3_S, two B70s with expert parallel, 1 x 200k, see
[../README.md](../README.md)) landed in one of two speeds per engine start, and stayed there until restarted:

| Start mode | Median decode (4-prompt set) | Code prompt |
|---|---|---|
| fast | 78-89 tok/s | 99-117 |
| slow | 32-45 | 42-54 |
| in between | 54-59 | 67-76 |

Same binary, same config, same cards, same answers. The slow mode is ~2.4x slower on every prompt, prompt reading
included.

## Cause

**Windows' standby list (the file cache) filling RAM.** Purging it before each start made every start fast, in the
same hour that gave 0 fast starts out of 8 without it:

| Run (8 fresh starts each) | Fast starts | Medians (tok/s) |
|---|---|---|
| Normal starts, engine stopped with `QUIT` (clean) | 0 of 8 | 36.0, 55.4, 40.6, 41.5, 54.8, 45.0, 35.8, 39.4 |
| Standby list purged before each start | **8 of 8** | 85.0, 89.1, 85.2, 84.4, 85.0, 86.3, 86.2, 83.0 |

It also explains the rest of the data: right after a reboot the first 3 starts were fast (RAM empty), then 4 of the
next 5 slow; earlier the rate drifted from mostly slow to mostly fast over an evening. Before the purge run, the
standby list held ~71 GB of the machine's 96 GB.

Mechanism (inferred, not measured directly): the two cards exchange expert results through pinned host USM. Pages
for a new pinned allocation come from wherever free memory is; once the standby list holds most of RAM they are
repurposed, scattered pages, and the cards' accesses to that buffer get slower.

## How it was found

`STRATA_DECODE_TIMING=1` + `STRATA_VERIFY_PROFILE=1` (serve mode only) print a per-request GPU stage table. Fast and
slow starts differ in one stage: the expert-parallel exchange ("VRAM hits", which includes the wait for the helper
card), ~4x slower. Card 0's other stages and the MTP draft are identical.

Ruled out along the way (no difference between fast and slow starts): host core pinning (`STRATA_HOST_CORE=last`),
the PCIe link, host USM bandwidth and small-copy latency (28.4 / 26.7 GB/s, 3.7 us on every card, every start),
CPU spin, GPU compute and clocks (2,800 MHz on both cards), which physical cards, leftovers of killed runs (a clean
`QUIT` stop does not help), and a reboot by itself.

## The fix in use: restart if slow, purge first

`0001-serve-restart-if-slow-guard-with-standby-purge.patch` (against `sycl/serve/server_intel.py`) wraps the engine
start. After READY it times a short greedy probe (a 39-token chat-templated code prompt, 160 tokens) and starts the
engine again when decode is below a floor. It is off unless the engine config's `env` sets it:

| Key | Meaning |
|---|---|
| `STRATA_SPEED_GUARD_MIN` | floor in tok/s (we use 85: fast probes read 91.9-97.2, slow 38.7-47.9, in between 74-83) |
| `STRATA_SPEED_GUARD_TRIES` | starts at most (default 3; the last one is kept whatever its speed) |
| `STRATA_SPEED_GUARD_PURGE=1` | before a retry, run `purge_standby.ps1` (next to the server) |
| `STRATA_SPEED_GUARD_TOKENS` / `_NEW` | the probe's token ids file (default `speed_probe.tok` next to the server) / tokens to generate |

Each probe and purge is logged as a `[speed-guard]` line in the engine log. Results: with floor 90 (no purge), 6 of 6
starts ended fast after catching 3 slow ones; with the purge, a forced retry went 47.9 -> purge -> 100.7 tok/s. The
cost lands only on slow starts: the start after a purge reads the model from disk again (~77 s instead of ~32 s), and
other models lose their cached file pages.

`purge_standby.ps1` empties the standby list the way RAMMap's "Empty Standby List" does: it enables
`SeProfileSingleProcessPrivilege` and calls `NtSetSystemInformation(SystemMemoryListInformation,
MemoryPurgeStandbyList)`. Needs an elevated token (an admin shell, or a LocalSystem service such as llama-swap under
NSSM). No download.

`start_ab.py` is the harness behind every table here: N fresh server starts on a spare port (`PORT`, default 8090), 4 prompts each, with
`FLOOR`, `CLEAN=1` and `PURGE=1` switches (see its header).

## Not done

An engine-side fix that would make the purge unnecessary: allocate the exchange buffers so their physical layout
does not depend on the file cache (for example large pages, or one allocation made early and reused).
