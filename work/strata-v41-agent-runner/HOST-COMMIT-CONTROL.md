# Host commit tracks model size — the small-model control (2026-10-28 07:40)

> ## ⚠️ VERDICT WITHDRAWN 2026-10-28 08:15 — see `CONTENTION-CORRECTION.md`
>
> The conclusion below ("1017 cannot load here, shortfall 33–43 GB") was drawn from measurements
> taken **while another agent was running `llama-bench` against the same 1017 pack on the same
> machine**, holding 129.66 GB of commit against a 154.8 GB limit. A foreign `qual.bat` and
> `final.bat` were also running 1017 servers on ports 9034/9040.
>
> **What survives:** the control's own arithmetic (§1) is sound and is the useful part —
> `priv 19.66 GB` vs `ws 27.71 GB` on a 17.28 GB model proves `priv` is *anonymous commit*, not
> resident RAM, and that file-backed mmap pages count in WS but not in private commit. That kills
> the "WDDM charges VRAM to commit" hypothesis.
>
> **What is withdrawn:** §3's shortfall arithmetic and the "1.15× multiplier" claim. They were
> derived from contended peaks.

Answers the open question left in `WATCHDOG-KILL-FINDING.md` §6: **is the host-side commitment a
property of this SYCL path, or specific to the 1017 pack?**

**Answer: it is a property of the path. Private commit ≈ 1.14 × model size on a known-good model
that loads and serves successfully.** 1017 does not fit on 96 GB for arithmetic reasons, not
because of a bug, a patch, or a flag.

-

## 1. The control

Same build (`de5122d`, `C:\llamacpp-v41\build-sycl`), same SYCL backend, same
`GGML_SYCL_SUPPORT_LEVEL_ZERO_API=ON`, mmap enabled (`-lm auto`), `-ngl 99`. Only the model differs.

| | Control | 1017 |
|---|---|---|
| Model | Qwen3-Coder-30B-A3B-Q4_K_M | DeepSeek-V4.1-Flash-1017 IQ2_XXS |
| Size on disk | **17.28 GB** | **128.74 GB** |
| Private commit | **19.66 GB** | 121–133 GB |
| Working set | 27.71 GB | 77–86 GB |
| **priv / model** | **1.138** | **0.94 – 1.04** |
| Outcome | `health 200`, serving | killed by watchdog |

The control loaded, bound its port, and returns `health 200`. It is a working model on the same
binary. Its private commit is **1.14× its file size**.

1017's ratio is 0.94–1.04× — the same order, bounded below by 1. Every load mode lands there:

| 1017 run | `-lm` | priv | ratio |
|---|---|---|---|
| `srv-v41` | `none` | 133.4 GB | 1.036 |
| `-ngl 40` | `none` | 129.9 GB | 1.009 |
| `srv-lmauto` | `auto` | 121.2 GB | 0.941 |
| `srv-dio` | `dio` | 129.9 GB | 1.009 |

**Changing the load mode does not change the host cost.** `-lm none` (explicit read, no mmap),
`-lm auto` (mmap), and `-lm dio` (direct I/O) all commit roughly one model's worth of host memory.

-

## 2. What this settles

**It is not loader staging that a flag could remove.** If it were, `-lm auto` — which lets the
kernel page the file in on demand instead of reading it into anonymous memory — would have
collapsed the host cost. It reduced it by ~11% (133.4 → 121.2 GB) and no further.

**It is not 1017-specific.** A 17 GB model on the same binary shows the same 1:1 relationship.

**It is not the patches.** The control uses the same patched `llama.dll`.

The remaining host cost is the SYCL/xe path keeping a host-side copy of tensor data alongside the
device buffer. The mitigation documented at `ggml/src/ggml-sycl/common.cpp:95-96` — using Level Zero
`zeMemAllocDevice` to avoid "DMA-buf/TTM system RAM staging in the xe kernel driver" — is compiled
in and nominally enabled (`GGML_SYCL_USE_LEVEL_ZERO_API` defaults to 1 at `ggml-sycl.cpp:458`), but
does not eliminate it. That is a driver/backend property, not a llama.cpp flag.

-

## 3. The arithmetic, stated plainly

| Constraint | Value |
|---|---|
| RAM | 95.9 GB |
| Host cost multiplier | ~1.0–1.14 × model size |
| **Largest model that can load** | **~84–96 GB**, and it needs headroom to actually run |
| 1017 pack | 128.74 GB |
| **Shortfall** | **~33–43 GB** |

The 1017 pack needs roughly **1.5× the machine's RAM** to load under this backend. No combination
of `-ngl`, `-ts`, `-ot`, `--cache-ram`, `--ctx-checkpoints`, or load mode closes a 35 GB gap. The
device side was never the problem — 119.4 GB of buffers fit comfortably in 128 GB of VRAM.

-

## 4. Consequences for the plan

1. **Stop tuning 1017 on this box.** It cannot load here. Further flag permutation cannot close a
   35 GB host-memory gap.
2. **The two viable paths:**
   - a pack small enough that ~1.15× its size fits in ~80 GB (i.e. **≤ ~70 GB**), or
   - a box with **~160 GB RAM** for the current 128.74 GB pack.
3. **The cheapest way to test path (a)** is an existing smaller DeepSeek-V4 pack rather than a new
   quantisation. `DeepSeek-V4-Flash-0731` is already on the box and already works — but note it is
   `deepseek4`, not `deepseek41`, so it does not exercise the 1017 architecture. That distinction
   matters if the goal is proving the `deepseek41` path.
4. **The Qwen and 0731+DSpark tracks are unaffected** and remain the useful production work.

-

## 5. Method notes

- Control ran with `-lv 2`, so `model buffer size` lines are absent from its log. The measurement
  is from `PrivateMemorySize64` / `WorkingSet64` at steady state (six consecutive samples flat at
  `priv=19.66 GB` from 07:37:11 to 07:37:37), plus `health 200`.
- Sampler reads `Win32_PerfRawData_PerfOS_Memory.AvailableBytes` (true available, including
  standby) alongside the watchdog's `FreePhysicalMemory`. Both were recorded; on the 1017 runs both
  reached ~0, confirming the watchdog floor is not a false positive.
- Every 1017 run in this document was terminated by `C:\llama-swap\ram-watchdog.ps1`, evidenced by
  its log lines with pid, private bytes and free RAM at kill time.
