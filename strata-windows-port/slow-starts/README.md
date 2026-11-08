# Strata on Windows: the slow-start lottery (cause: card 0's own expert rows in host memory)

The served Strata build (Qwen3.8-Flash-Next GSQ-RCO IQ3_S, two B70s with expert parallel, 1 x 200k, see
[../README.md](../README.md)) landed in one of two speeds per engine start, and stayed there until restarted:

| Start mode | Median decode (4-prompt set) | Code prompt |
|---|---|---|
| fast | 78-89 tok/s | 99-117 |
| slow | 32-45 | 42-54 |
| in between | 54-59 | 67-76 |

Same binary, same config, same cards, same answers. The slow mode is ~2.4x slower on every prompt, prompt reading
included.

## Cause and fix (2026-11-07)

**Card 0 wrote its own expert results into host memory.** With `STRATA_NIGHT_EP_PSUM=1` (in the served config), card 1
returns one weighted-sum row per token in its own region (`ep_psum0_`) and never touches card 0's row buffer
`parts_`. But `Verifier::ep_init` still pointed `parts_` at the exchange region `ep_rows0_`:

```cpp
if (!ep_verify_ && !self) parts_ = ep_rows0_;
```

On Linux that costs nothing, because the region is card 0's VRAM, shared with card 1 through Level Zero IPC. Windows
has no peer access between B70s, so this port allocates the exchange regions as **host USM**. As a result, every grouped
expert launch on card 0 wrote its rows over PCIe, and the combine read them back. How fast that went depended on the
pinned pages a process happened to get. That is why speed was fixed per start, why it drifted with the state of
RAM, and why purging the file cache seemed to help (it changes which pages a new process gets).

Fix: keep `parts_` in VRAM when PSUM is on (`0002-ep-psum-own-rows-in-vram.patch`, 6 lines in `verify.cpp`;
`STRATA_EP_PARTS_HOST=1` restores the old path). Sent upstream as
[hotschmoe/Strata#1](https://github.com/hotschmoe/Strata/pull/1).

| 8 interleaved fresh starts per arm, no purge, file cache at ~90 GB | Median decode per start (tok/s) |
|---|---|
| fix | 106.5, 106.6, 107.5, 106.3, 104.2, 106.0, 107.8, 104.8 |
| old path (same binary, `STRATA_EP_PARTS_HOST=1`) | 79.3, 82.8, 54.1, 82.6, 80.7, 82.6, 56.8, 59.4 |

The fix is also ~30% faster than the old *fast* starts, because those paid for the PCIe round trip too. Greedy output
was identical to the unpatched build on 4 fixed prompts. Served through llama-swap: 111-133 tok/s on code / explain /
summary requests. The restart-if-slow guard and the standby purge below are retired.

How it was found: per-stage stamps on **both** cards. A `gpu_stamp` on card 1's queue at each step of its exchange,
plus one on card 0 just before its wait, all on the same host clock. Card 1's side and the flag handshake were
identical in fast and slow starts:

| ms per window (sum over layers) | fast start | slow starts |
|---|---|---|
| card 1: copy inbox / experts / send | 0.19 / 5.1 / 0.4 | 0.19 / 5.1 / 0.4 |
| card 0: waiting for card 1 | 0.0 | 0.0 |
| card 0: flag seen after both done | 0.17 | 0.18 |
| **card 0: its own grouped experts** | **11.5** | **31.7-50.9** |
| card 0 with the fix | 4.4 | - |

GPU memory placement counters (dedicated / shared per card) were identical in every start, so Windows was not
moving VRAM to system memory. One aside: an earlier test that only changed how the exchange regions are allocated
(2 MB alignment, an arena, uncached) showed no effect over 8 starts. 3 starts per arm had suggested a win, so this
lottery needs at least 8 interleaved starts per arm to read.

## Second leak: the prompt read (2026-11-07)

Prompt reading had its own lottery after the decode fix. A 37,318-token prompt read at 1,552 or 792 tok/s on the old
build depending on the start, and at 704 or 796 on the decode-fixed one. The cause was the same pattern on card 1's side.
With `STRATA_EP_PREFILL_REDUCE=1` (served config), card 1 sums its own expert rows for each prompt chunk and sends card 0
only the sums. Its rows buffer `rows_reg` (800 MiB: the gathered inputs under the gather alias, and the experts'
outputs) is never read by card 0 in that mode, yet `Prefill::set_ep_peer` allocated it as a shared exchange region.
On Windows that is host memory, so every expert GEMM on card 1 went across PCIe.

Fix (`0003-ep-prefill-rows-private.patch`): a new `ep_region_alloc_private` in `ep_mem.hpp` (a plain
`zeMemAllocDevice` on the owner, no mapping for the other card) is used for `rows_reg` when reduce is on. If it does
not fit, it falls back to the shared region with a log line. `STRATA_EP_PREFILL_ROWS_HOST=1` restores the old allocation.

| 37,318-token prompt, 4 fresh starts per arm, same binary | Prompt read (tok/s) | First token |
|---|---|---|
| private rows buffer | 1,557, 1,561, 1,476, 1,570 | ~24 s |
| shared region (`STRATA_EP_PREFILL_ROWS_HOST=1`) | 777, 775, 780, 774 | ~48 s |

Decode is unchanged (111 / 155 tok/s on the bench's code prompts, 107-108 right after the long prompt). Greedy output
was identical to the previous build on 5 fixed prompts, including a ~37k-token one. Card 1's free VRAM after setup
goes from 2,060 to 1,264 MiB. Served through llama-swap: 1,576 tok/s on the long read, 130 tok/s mean decode on the
7-prompt bench, answer checks correct.

## First theory (2026-11-01, superseded): the file cache

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
repurposed, scattered pages, and the cards' accesses to that buffer get slower. (Partly right: the speed did depend
on the pinned pages. But the traffic that should not have been there at all was card 0's own rows; see above.)

## How it was found

`STRATA_DECODE_TIMING=1` + `STRATA_VERIFY_PROFILE=1` (serve mode only) print a per-request GPU stage table. Fast and
slow starts differ in one stage: the expert-parallel exchange ("VRAM hits", which includes the wait for the helper
card), ~4x slower. Card 0's other stages and the MTP draft are identical.

Ruled out along the way (no difference between fast and slow starts): host core pinning (`STRATA_HOST_CORE=last`),
the PCIe link, host USM bandwidth and small-copy latency (28.4 / 26.7 GB/s, 3.7 us on every card, every start),
CPU spin, GPU compute and clocks (2,800 MHz on both cards), which physical cards, leftovers of killed runs (a clean
`QUIT` stop does not help), and a reboot by itself.

## The old workaround (2026-11-01, retired 2026-11-07): restart if slow, purge first

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

## Engine-side fix

Done 2026-11-07, see [Cause and fix](#cause-and-fix-2026-11-07). The idea listed here before (allocate the exchange
buffers so their layout does not depend on the file cache) was tested and did not help; the real fix was to stop
card 0's own rows from going through the exchange region at all.
