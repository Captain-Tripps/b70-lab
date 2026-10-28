# Host-mirror probe (2026-10-28)

Question: on Windows SYCL / Level Zero, why does every GB of model weights on the GPUs also cost
~1 GB of host RAM?

`mirror_probe.cpp` allocates 16 GiB on one B70 in 1 GiB chunks (SYCL `malloc_device` or raw
`zeMemAllocDevice`, the path llama.cpp uses), fills it on-device, copies host data in from a
pageable or pinned 256 MiB buffer, frees the host buffer, idles, reads back, and frees. After each
step it prints process private bytes, working set, and system commit/available. Raw output:
`probe-results.txt`.

## Result: identical in all four modes

| Step | Private | Working set | System available |
|---|---:|---:|---:|
| baseline | 0.62 GiB | 0.08 GiB | 84.2 GiB |
| 16 GiB device alloc | **16.65 GiB** | **0.08 GiB** | 84.1 GiB |
| device memset | 16.66 | 0.08 | 84.1 |
| host→device copy (16 GiB) | 16.92 | 0.34 | 83.9 |
| host buffer freed, idle 15 s | 16.68 | 0.09 | 84.1 |
| device freed | 0.90 | 0.34 | 83.9 |

- **The driver charges device memory to process commit 1:1 at allocation time, but none of it is
  resident.** Working set and system available don't move. It is a commit reservation only, which
  the pagefile can back (commit limit here is ~151 GB).
- **Copies do not leave a host copy behind,** pageable or pinned.
- So the resident ~60 GB seen when serving 1017 is **not** the driver or WDDM.

## Where the resident RAM actually comes from

`src/llama-mmap.cpp`: on Linux, `unmap_fragment()` `munmap`s the file ranges of tensors that were
uploaded to a GPU. **On Windows it is a no-op** (`GGML_UNUSED(first); GGML_UNUSED(last);`). With
`-lm auto`, every GPU-bound tensor is read through the memory-mapped file, and those pages stay in
the server's working set after upload. They're clean file pages (reclaimable in principle), but they
occupy RAM the CPU experts need as page cache. That matches every run: working set at health ≈ GPU
total (Qwen 18 GB, 1017 59 GB).

## Validation on 1017 (`-ncmoe 24`, one `EmptyWorkingSet` call right after health 200)

| | Working set | Available |
|---|---:|---:|
| health 200, before trim | 59.2 GB | 24.2 GB |
| 5 s after trim | **0.0 GB** | **82.6 GB** |
| end of bench (experts paged in) | 41.4 GB | 42.1 GB (never lower) |

Private memory stayed at 62 GB throughout (the commit-only reservation). **Diagnosis confirmed:** the
58 GB was reclaimable file pages left behind by the Windows no-op `unmap_fragment`.

Bench with the trim vs. without (`box-s17.ps1` run):

| | without trim | with trim |
|---|---:|---:|
| warm prefill (189 tok) | 6.98 tok/s | 7.26 tok/s |
| warm decode | 0.93 tok/s | **1.01 tok/s** |

Only +4–8%. With NVMe pressure gone (available never below 42 GB), **the remaining limit is CPU
compute of the 24 CPU-side expert layers**: llama-server used 11.8 cores, exactly `-t 12`, on a
24-core / 48-thread EPYC 7402P. The host sat at about 27% total, and the GPUs mostly idled waiting
for it (one card around 15%). Next lever: a `-t` sweep (24, 36, 46) with the trim.

## Thread sweep (`box-s19.ps1`): same config + trim, only `-t` changed

| `-t` | avg cores used | cold decode | warm prefill (189 tok) | warm decode |
|---:|---:|---:|---:|---:|
| 12 | 11.8 | 0.97 | 7.26 | 1.01 |
| 24 | 19.7 | 1.70 | 11.23 | 1.84 |
| 36 | 29.1 | 1.97 | 12.36 | 2.20 |
| **46** | 36.5 | 2.16 | **12.74** | **2.46** |

All outputs were coherent. **`-t 46` is the best tested: 2.4× decode and 1.75× prefill against the
session's earlier `-t 12` numbers.** Gains per thread fall off past 24 (one per physical core) but are
still positive at 46. Available RAM never went below 42 GB, so these runs were not disk-bound.

Remaining gap: 2.5 tok/s is still far below what about 100 GB/s of DDR4 bandwidth would allow for
IQ2 experts. The leading suspect is per-layer GPU↔CPU hand-off overhead in SYCL on Windows (24
round trips per token). Next discriminating test: 1017 CPU-only (`-ngl 0 -t 46`). If that comes close to
2.5 tok/s, the hybrid's hand-offs are the cost.

## Implications

- The fix is in llama.cpp, not the OS: on Windows, `unmap_fragment` should drop those pages from the
  working set. `VirtualUnlock` on the range, or `EmptyWorkingSet` once after load as a blunt
  version, sends them to standby, so they count as available again.
- The commit charge is real but not resident, so the watchdog's commit trip should compare against
  the **commit limit**, not physical RAM, before trying configs with more on the GPUs.
- Expected effect on 1017 at `-ncmoe 24`: about 60 GB more page cache for 71 GiB of CPU experts, so
  most expert reads should come from RAM instead of NVMe.

## CPU-only control (`box-s20.ps1`): `-dev none -ngl 0 -t 46`, same bench

| | hybrid `-ncmoe 24` + trim (s19) | CPU only (s20) |
|---|---:|---:|
| cold decode | 2.16 | 1.50 |
| warm prefill (189 tok) | 12.74 | 8.20 |
| warm decode | **2.46** | **1.65** |
| avg cores used | 36.5 | 43.8 |

Output was coherent. The CPU-only run was not fully warm: the working set grew to 77 GB, available RAM fell
to 7 GB, and disk reads of 50-300 MB/s continued through the warm decode. All 129 GB of weights do not fit
in page cache, so its numbers are slightly pessimistic.

**The hybrid's GPU side is cheap; CPU expert compute is the bottleneck.** If per-layer CPU cost were the
same in both runs, CPU-only covers 40 expert layers at 1.65 tok/s, so 24 CPU layers alone would give about
2.75 tok/s. The hybrid reaches 2.46, which means the 16 GPU layers, attention and all hand-offs together
cost about 43 ms per token (~10% of the token time). The hand-offs are not the main gap.

Implication: decode scales with how many expert layers leave the CPU. Now that the trim removes the
host-RAM cap, the next lever is lower `-ncmoe` (more layers on the GPUs, up to VRAM). Before that, the
watchdog's commit trip must compare against the commit limit, because the commit-only GPU reservation
grows ~1:1 with GPU weights.
