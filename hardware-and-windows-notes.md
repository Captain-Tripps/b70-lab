# Hardware and Windows notes

Things about running Arc Pro B70s for LLM inference on Windows 11 that cost me time. Machine and driver versions are
in the [README](README.md).

## Driver moves an idle process's VRAM to system RAM

About 70 seconds after a llama-server goes idle, the Windows Arc driver starts moving that process's VRAM into system
RAM (~1 GB/s). With 4 cards (~115 GB of VRAM in use) and 64 GB of RAM, the box ran out of RAM 3-5 minutes after every
load and my RAM watchdog killed the server. Observed for llama.cpp's Flash-Next, DeepSeek V4 and gpt-oss-120b servers.

- A tiny request every 45 s prevents it. GPU activity from another process does not.
- Fix in my fork: `GGML_SYCL_IDLE_HEARTBEAT_SEC=30` starts a thread that submits a trivial kernel to each used queue
  when no graph has run for 30 s ([llama.cpp-sycl/fork/misc/patch_idle_heartbeat.py](llama.cpp-sycl/fork/misc/patch_idle_heartbeat.py)).
  With it: 5+ minutes idle, RAM flat, first request after idle 1-3 s.
- Driver 8805 when found; not re-checked without the heartbeat on 8976.
- Re-validated 2026-10-21 on driver 8976 with the 105 GB GLM-5.3 Maya-M arm (4 cards, 128k context, 96 GB host
  RAM): a 300 s idle soak with the heartbeat on held dedicated VRAM dead flat (114.58 GB total) with a working set
  of 4.5 GB, and the first request after idle answered in 0.5 s. Without the heartbeat, the same class of arm paid a
  167 s page-in on its first request after idle ([glm-5.3/HILLCLIMB-2026-10-20.md](glm-5.3/HILLCLIMB-2026-10-20.md)).
  The heartbeat string is present in `ggml-sycl.dll` of every runtime I checked; it costs nothing to set.
- Gotcha that survived three days of debugging: on the bench box, 19 of 20 llama-swap model entries set
  `GGML_SYCL_IDLE_HEARTBEAT_SEC=30`; exactly one did not - the production GLM entry - and that was the model that
  kept dying. Grep your config before blaming the next build.

## Silent spill into system RAM when a config does not fit

- WDDM lets GPU allocations overflow into shared (system) memory instead of failing. Speed collapses (gpt-oss-120b
  2 cards at 131k f16 KV: decode 13 vs 60-70 tok/s) and host RAM drains fast (~1.5-1.7 GB/s during warmup).
- With `GGML_SYCL_HOST_MEM_FALLBACK` builds, allocations that do not fit go to host RAM without even showing as GPU
  "shared usage". Watch **available host RAM**, not the GPU counters.
- Four back-to-back loads of a config that did not fit hard-hung the machine (Kernel-Power 41) when it had 31 GB RAM.
  I now run test servers under a guard that kills them below ~10 GB available RAM, one heavy config per run.
- ~2-3 GB of "shared" GPU memory per model in Task Manager is normal steady state (fixed host buffers), not a spill.
- A card that also drives the desktop loses 0.2-0.9 GB to dwm and apps; leave margin on that card or drive the
  display from another adapter (e.g. the motherboard's onboard VGA).
- Per-process VRAM: `Get-Counter '\GPU Process Memory(*)\Dedicated Usage'`.
- llama.cpp's automatic fit can over-project and pack cards lopsided; check per-card memory after load and look for
  `fit_params` in the server log. For big multi-card models I pin placement with `-fit off -ngl 99 -ts ...`.

## Private bytes is not physical RAM

- A perfectly healthy GLM arm sat at 123 GB of **private bytes** while its physical working set was 4.5 GB and
  76 GB of host RAM was free. llama.cpp's big multi-card allocations reserve address space against GPU memory, so
  commit charge balloons with no RAM behind it. Reading private bytes as "memory used" fails healthy runs; an
  earlier watchdog design did exactly that and burned a week of A/B tests on it.
- Judge an arm by: available physical RAM, the process **working set**, and per-adapter dedicated VRAM from
  `Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage'`. If dedicated VRAM total collapses while the server is
  idle, that is driver demotion, not a leak.

## WHEA Id 22 on every boot - degraded memory path (2026-10-21)

- The bench box logs `WHEA-Logger` Id 22, "A fatal hardware error has occurred. Component: Memory, Error Source: BOOT,
  Error Type: 15" on **every boot** (four times on Oct 14, again Oct 17, 19, 21). Reseating DIMMs did nothing; the
  fault is on the CPU socket, and a replacement CPU is on order.
- Visible RAM dropped from 128 GB (7x16 Micron) to 95.9 GB (6x16 Kingston `36ASF2G72PZ-2G1A2` DDR4-2133). WMI on
  this board reports `DeviceLocator` "DIMM 0" for everything and blank `SMBIOSMemoryHandle`, so you cannot map
  sticks to channels from WMI - believe the count, not the labels.
- Any build A/B that crosses that boundary is comparing two different machines. This single fact invalidated the
  "memory regression" hunt recorded in [glm-5.3/ROADMAP.md](glm-5.3/ROADMAP.md). Check `WHEA-Logger` and installed
  RAM **before** believing any memory cliff on this box.

## Building llama.cpp SYCL on Windows

- oneAPI 2026.0 `icx`. The B70's chip is BMG-G31; llama.cpp here is AOT-built for the `bmg_g21` target, which runs on
  it. (Strata's AOT target is `bmg-g31`; it is built JIT here, see below.) `setvars.bat` was broken on this install; I set up `vcvars64` plus the
  oneAPI component `env\vars.bat` files by hand.
- Build with `GGML_NATIVE=OFF` and an explicit ISA (AVX, AVX2, FMA, F16C, no AVX-512). Binaries built with
  `-march=native` on a Ryzen with AVX-512 died with `0xC000001D` (illegal instruction) at backend init after the move
  to an EPYC 7402P (Zen 2, no AVX-512).
- The AOT build failed with "IGC: Internal Compiler Error" while a large model was loaded: the GPU compiler needs
  VRAM. Unload models before building.
- Executables die with `0xC00004BC` if the oneAPI runtime DLLs are not on `PATH` or next to them.
- AOT can miscompile: oneAPI 2026.0's `ocloc` AOT build for `bmg-g31` produced wrong results in Strata's batched
  int8 attention, while the same sources JIT-compiled by the driver (32.0.101.8976) were bitwise correct. When a
  kernel's output is wrong and the code looks right, try a JIT build. See [strata-windows-port/](strata-windows-port/).
- After a Level Zero SDK update (1.28.2 -> 1.32.0) CMake's cached paths had to be fixed by hand.

## Level Zero on Windows

- No IPC and no peer access between B70s; a kernel touching another card's memory gives `DEVICE_LOST`. Host USM in
  one shared context works for all cards. Card-to-card traffic goes through host memory. See
  [reproducers/](reproducers/) and [strata-windows-port/](strata-windows-port/).
- Several threads submitting kernels plus oneMKL can deadlock in the driver. See [reproducers/](reproducers/).
- `queue::memset` was not reliably ordered against following kernels in my code; reset buffers from
  a kernel or wait first. oneMKL calls also needed explicit waits around them.
- The v2 Level Zero adapter (default) is faster than v1.
- Driver 32.0.101.8976 (2026-10-11) raised prompt reads on my pipeline runtimes ~1.6-2.4x vs 8805, with roughly
  twice the peak GPU power.

## Xe2 detail

`ggml-sycl.cpp` estimates the number of Xe cores as `max_compute_units / 16`, which assumes 16 EUs per core. Xe2 has
8, so the B70 reports 16 instead of 32. The flash-attention split heuristic is tuned around that value; see
[llama.cpp-sycl/](llama.cpp-sycl/) (patch 0008).

## Serving tips (llama-server)

- **Prompt cache on recurrent / compressed-state models** (Qwen3.8 DeltaNet layers, DeepSeek V4, GLM): the server can
  only resume from a context checkpoint, and it creates one per request at the **end** of the prompt. When a client
  sends several requests that share a long prefix and differ only at the end, the previous request's checkpoint lies
  past the point where the next one diverges, so the server re-reads almost the whole prompt. Fix on the client side:
  first send one request with only the shared prefix (max_tokens 1). Its checkpoint lands exactly at the boundary.
  On a 5-request job with a ~17k-token shared prefix on DeepSeek V4: ~154 s -> ~64 s of prompt work.
  `--checkpoint-min-step` did not help.
- **Cap reasoning.** Flash-Next once produced 80k reasoning tokens for one request; GLM-5.3 defaults to maximum
  reasoning effort. `--reasoning-budget N` on the server, or per request `reasoning_budget_tokens`,
  `chat_template_kwargs.enable_thinking=false`, `reasoning_effort`.
- Model swaps (llama-swap or similar) drop the prompt cache. Long cached jobs need the machine to themselves.

## Windows housekeeping

- Power plan "High performance" and BIOS C-states off helped decode on the EPYC host (gpt-oss-20b 98 -> ~104-110 tok/s
  on one card).
- Windows' OpenSSH server kills processes started inside an SSH session when it ends; start long jobs through WMI
  (`Win32_Process.Create`) or a scheduled task.
- Hugging Face `hf` / Xet downloads hung mid-file on this box; a `curl -C -` resume loop works.
- `llama-bench` here takes `-lm dio` for direct-I/O loading; with mmap, Task Manager shows file-backed pages as if RAM
  were full.
- Mixing RDIMM types (2Rx8 with 2Rx4) on the ROMED8-2T made the BIOS disable the new modules. The board manual's
  suggested slot layout for 4 DIMMs was wrong for this board revision; check the memory population table.
