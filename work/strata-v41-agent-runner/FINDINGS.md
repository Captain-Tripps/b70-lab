# Strata V4.1 on B70 — findings ledger

Living document. **Winners** are decisions/facts that moved the port forward. **Losers** are
approaches that were tried or assumed and did not hold. Both are recorded, because the losers are
the expensive part to rediscover.

Append-only in spirit: when something changes, add a revision note rather than silently editing,
so a later session can see what was believed when.

Last updated: 2026-10-27 (session 2)

---

## Status at a glance

| Gate | State | Blocker |
|---|---|---|
| CHECK-100 | PARTIAL | fresh-session resume NOT_RUN |
| CHECK-101 | PARTIAL | upstream fetch, PCIe links, toolchain PATH |
| CHECK-102+ | NOT_RUN | not started |

Host is **stable-but-degraded**: 95.87 GiB usable RAM, 4× B70 present, 37.6 h clean uptime.

---

## WINNERS

### W-001 — Strata tree is `%USERPROFILE%\strata-win`
Remote `github.com/hotschmoe/Strata.git`, branch `win-port`, `v0.1.44.1-26-g1c360526`, 2200
commits, not shallow. Found by searching for directories matching `strata` and for `.git` repos,
not by trusting the plan's path list.

**Why it matters:** every later step patches this tree. Knowing it is the tree is the difference
between real work and editing a stranger's checkout.

### W-002 — `1c360526` resolves to `1c360526bce659f45cec60b2e36c46b7770c5bf1`, and it is HEAD
The plan described this as an "abbreviated base" the Windows patches target, implying an older
commit. It is not older — it is the current `win-port` tip. Date 2026-10-16.

**Consequence:** the 29 uncommitted files are local work sitting *on top of* that base. There is no
mystery commit to hunt for.

### W-003 — The 29 uncommitted files are captured and safe
`rescue/working-tree.patch` — 20,189 bytes, ASCII, 18 files, +157/−23, produced with
`git diff HEAD --output=...` so git wrote the bytes itself. Verified with
`git apply --check --reverse` → applies cleanly. Also captured: `status.txt`, `untracked.txt`,
`provenance.json`.

**Why it matters:** this was the single irreversible-if-lost item. It is now in git, off-box.

### W-004 — WHEA Id 22 is a boot-time event, not a runtime one
One event per boot, ~23 s after boot, then zero for the life of the uptime. 37.6 h continuous
uptime produced exactly one event. This supersedes the earlier "no stable baseline, pause heavy
testing" reading.

**Consequence:** heavy GPU work is not gated by expected runtime instability. 95.87 GiB is the
budget. Any future RAM change invalidates A/B comparisons across that boundary.

### W-005 — RAM reconciled: 6 × 16 GiB = 95.87 GiB usable
DIMMs: 6 × Micron `36ASF2G72PZ-2G1A2`, 2133 MT/s, channels A–F populated, 2 slots empty.
The plan's "128 GB" is board capacity, not installed memory. The historical 95.9 GB figure matches
today exactly; the 112 GB figure is not reproduced.

### W-006 — Desktop is on the BMC, so no B70 pays the compositor tax
Display adapter is `Microsoft Basic Display Adapter` (ASPEED, `VEN_1A03&DEV_2000`). All four B70s
are purely compute. The lab notes warn that a card driving the desktop loses 0.2–0.9 GB to
`dwm`/apps; that does not apply here.

### W-007 — PowerShell 5.1 / .NET Framework 4.0 changes the runner design
`ProcessStartInfo.ArgumentList` does not exist. argv quoting is implemented per
`CommandLineToArgvW`. Separately, `powershell.exe -File` cannot bind an array parameter from
separate tokens, so argv travels in a JSON file.

**Why it matters:** both were found by running the suite, and both silently corrupt paths with
spaces if you get them wrong.

### W-008 — `git --output=` is the only reliable way to capture a patch on Windows
`git diff > file` under PowerShell 5.1 produced UTF-16 with git's stderr interleaved — a corrupt
patch that `git apply` rejected. `git diff --output=<path>` lets git write the bytes.

---

## LOSERS

### L-001 — Four directories named in the plan are not the source tree
| Path | What it actually is |
|---|---|
| `C:\llama-sycl` | prebuilt llama.cpp SYCL binaries; no `.git` |
| `C:\llama-sycl-new` | llama.cpp build/bench workspace; no `.git` |
| `C:\llama-swap` | llama-swap configs + corpus; no `.git` |
| `C:\Models` | GGUF model store |

**Why recorded:** a future session will see these names in the plan and be tempted again.

### L-002 — No DeepSeek V4.1 engine files exist in the local tree
Searched `strata_control`, `ds4_model.cu`, `ds4_kernels.cu`, `ds4_iq.cu`, `ds4_gguf.cu`,
`ds4_os.hpp`, `dsv41_fit.py`, `docs/DEEPSEEK41.md` — zero hits.

**Consequence:** there is no "patch the existing ds4 sources" shortcut. STEP-003 starts from
upstream v0.2.6. This is the single most important thing to know before planning the port.

### L-003 — Pinned upstream `4b9e05a2…` is not in the local object store
Comparing the deployed tree to pinned upstream requires a `git fetch`. Not done — the session was
read-only and a fetch is a network operation.

### L-004 — `-AsArray` is PowerShell 7+, not 5.1
`ConvertTo-Json -AsArray` does not exist on Windows PowerShell 5.1. JSON arrays are assembled
explicitly. Same family of trap as W-007.

### L-005 — scp to GPU-BOX silently failed
`scp` of a `.ps1` to `/mnt/c/...` reported nothing and copied nothing; `ssh gpu-box 'cat > file' < local`
worked. Use stdin redirection for pushing small files to the GPU-BOX WSL interop path.

### L-006 — SSH to GPU-BOX lands in WSL2 bash, not Windows
`uname -a` → `Linux GPU-BOX … microsoft-standard-WSL2`. All Windows facts must come from
`powershell.exe` / `cmd.exe`. WSL output is not Windows evidence and must never be reported as such.

### L-007 — `$id` is a PowerShell alias for `$PID`
Using `$id` as a loop variable in the process-tree walker shadowed the automatic variable and
would have broken the "do not kill myself" guard. Renamed to `$procId`.

### L-008 — `powershell.exe <script.ps1>` without `-File` is `-Command`
It parses the path as a command and exits 1. Cost several test iterations; all fixtures now pass
explicit `-File`.

### L-009 — 21 GB free padding is thin on C:
`C:` has 52.81 GB free. A 257 GB model download does not fit there. `D:` has 639 GB free,
`E:` has 298 GB. Plan model staging to `D:`.

---

## OPEN QUESTIONS

| # | Question | How to answer |
|---|---|---|
| Q-001 | Which upstream commit corresponds to v0.2.6? | fetch origin, check tags |
| Q-002 | What do the 4 `strata-stall-*.dmp` crash dumps say? | inspect with WinDbg or `dotnet-dump`; may explain current build state |
| Q-003 | PCIe link width/generation per card | vendor tooling / dxdiag; no Windows CIM exposure found |
| Q-004 | UR adapter DLLs location | `ur_loader.dll` / `ur_adapter_level_zero.dll` not in System32 |
| Q-005 | Is the 0731 work in b70-lab applicable to 1017? | survey `deepseek-v4/`, `llama.cpp-sycl/fork/deepseek-*` |
| Q-006 | What is the Maya Linux port and what transfers? | user knows this; treat as primary source |

---

## APPLICABILITY: what the 0731 / Maya work gives us for 1017

This is the section that decides how much of the port is new work.

### The three codebases, and why they are not the same thing

| Track | What it is | Engine | Relevance to 1017 |
|---|---|---|---|
| **0731** (`deepseek-v4/README.md`) | DeepSeek-V4-Flash-0731 in the **llama.cpp SYCL fork** (r52) | llama.cpp | **High** — same model family, same MoE shape class, same hardware |
| **Maya** (`glm-5.3/README.md`) | GLM-5.3-Flash Maya-M **GGUF quants** on the llama.cpp fork | llama.cpp | **Medium** — quant + MMA patterns transfer, architecture does not |
| **Strata** (`strata-windows-port/README.md`) | Separate SYCL engine, currently Qwen3.8-Flash-Next | Strata | **High for Windows platform**, none for DeepSeek arch |

**Correction to an assumption worth stating plainly:** "the Maya port for Linux" in the request is not a
DeepSeek port. Maya is Project Maya's **GLM-5.3** GGUF quant set; Maya's own engine is CUDA-only and was
never ported — the lab brought GLM into the llama.cpp fork instead. What transfers from Maya is quant
selection and kernel patterns, not an architecture port.

### Transfers directly (proven on 0731, same silicon)

| Finding | Evidence | Why it applies to 1017 |
|---|---|---|
| IQ2_XS / IQ3_XXS MoE kernel (v3) | 2.0x down, 1.6–1.7x gate/up at 1 token; 2.2–2.3x at 4 | 1017's routed experts are the same block types |
| Routing fusion | 4,202 → 3,862 launches; ids identical 516/516; ppl 6.4661→6.4620 | Architecture-agnostic routing chain |
| Sparse flash attention + indexer GEMM | decode at 59k +22%, prompt +96% | 1017 has compressed sparse attention + lightning indexer |
| Cross-card pipeline | prompt 236→446 tok/s @59k, 211→406 @102k | Needs bounded queues (`PIPELINE_MAX_QUEUED=4`) |
| Shared-context host staging | Strata patch 0002, 2-card EP working on Windows | Windows has **no peer access** — this is the only path |
| WHEA/RAM budget discipline | 131k is the practical ceiling at 4x32 GB | Same 4x32 GB constraint |

### Transfers as warnings, not code

| Loser (from `rejected-ideas/`) | Number | Applies because |
|---|---|---|
| SYCL graph replay | 21.9 → 7.1 tok/s | Re-records every step; worse under MoE |
| Broad small-op fusion | ~1,000 launches = +2% | Launch cost ~1–3 us, not the bottleneck |
| Level Zero v1 adapter | decode 19.2 → 16.0 | Do not "fix" a problem by downgrading the adapter |
| Expert-only parallelism for 0731 | ceiling 1.12x plain / 1.19x DSpark < 1.4x go line | **This is the big one — see below** |
| Grouped expert verification | −5 to −10% | Cache already absorbed redundant reads |
| `ext_oneapi_memcpy2d` | 227 s vs 17 s | Copies row-by-row on Level Zero |

### The critical non-transfer: expert parallelism was measured and rejected

`deepseek-v4/PLAN-expert-parallel.md` is explicit: Track A (expert-only parallelism for 0731) reached its
go/no-go gate at A0 and **failed it** — ceiling 1.12x plain / 1.19x DSpark against a 1.4x threshold. The
profile found expert matmuls were only 14–22% of decode step time; small ops were ~50%.

**But** the Strata route is a different proposition, and the plan says so: Strata runs Qwen3.8-Flash-Next on
**2 cards** at ~98 tok/s decode / ~1,400 tok/s prompt, vs the fork on **4 cards** at ~61 / ~750. Strata wins
because it keeps all experts resident and does expert parallelism with a captured graph, not because expert
parallelism alone is faster in llama.cpp.

**Conclusion for 1017:** do not re-run the 0731 Track A experiment. The 0731 rejection does not invalidate
Strata's approach; it invalidates bolting expert parallelism onto the llama.cpp fork. Those are different
claims and the difference cost real time to establish.

### The hard constraint that decides everything

From `PLAN-expert-parallel.md`, measured:

| | 0731 (running) | 1017 |
|---|---|---|
| Params | ~280B | **~510B** (FP8) |
| UD-Q2_K_XL | 90 GiB — **fits** 4x32 GB | — |
| ~2.7 bits/weight | — | **~170 GB > 128 GB VRAM** |
| llama.cpp support | yes (`deepseek4`) | **no** (`DeepseekV41ForCausalLM` unsupported) |

So 1017 cannot run in the llama.cpp fork at all, and cannot fit 4 cards at 2.7 bpw without the
Engram-off-to-NVMe and CPU-overflow-expert design the Strata plan describes. **This is why Strata is the
route and not a preference.**

### What 1017 adds that 0731 never exercised

`~510B`, hidden 5120, 384 experts × 2304, 40 layers. New: **Engram** n-gram memory layers (layers 1, 14),
KV shared across layers, new compressed-attention ratios, 3 MTP layers, built-in DSpark draft, vision tower.

None of that has a counterpart in the 0731 tree. The port is genuinely new surface, not a re-parameterisation.

---

## NEXT SESSION STARTER

Read this file, then `TASK-STATE.json`, then `rescue/provenance.json`.

**Do not reset `%USERPROFILE%\strata-win`.** `rescue/working-tree.patch` is the only backup of
29 files of in-progress work.

**Overarching goal (from the operator, 2026-10-27):** get DeepSeek V4.1 Flash 1017 running on GPU-BOX,
ported using what the lab learned from the Maya/0731 work. The 0731 tree in `b70-lab` is the prior art;
`APPLICABILITY` above maps what transfers and what was already measured and rejected.

## REVISION LOG

| Date | Change |
|---|---|
| 2026-10-27 s1 | Initial ledger: tree located, base resolved, WHEA corrected, RAM reconciled |
| 2026-10-27 s2 | Patch captured and verified valid; 0731/Maya applicability mapped; expert-parallel rejection clarified as a llama.cpp-only result |
