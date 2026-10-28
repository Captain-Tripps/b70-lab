# Session handoff — strata-v41 agent runner

Written 2026-10-27 ~13:20 CDT; **revised 2026-10-27 ~14:10 CDT by the fresh session it was
written for**. That session ran, satisfied the resume check, and corrected one of the warnings
below. Sections marked **[Session 7]** carry its findings.

Read this before touching anything.

-

## 1. Copy-paste prompt for the new session

```text
Resume work/strata-v41-agent-runner in Captain-Tripps/b70-lab.

Read, in this order, before doing anything:
  1. work/strata-v41-agent-runner/HANDOFF.md      (this file - start here)
  2. deepseek-v4/strata-v41/PLAN.md               (the route and the boundaries)
  3. work/strata-v41-agent-runner/TASK-STATE.json (current gate state + corrected premises)
  4. work/strata-v41-agent-runner/FINDINGS.md     (winners/losers ledger; read the
                                                   "SESSION 3 - ROUTE DIVERGENCE" section)
  5. deepseek-v4/strata-v41/OPENCLAW-START.md     (what this task authorizes)

Then: verify prior artifacts before relying on them, inspect current git status, and continue
only the unfinished STEP-000/STEP-001 work. Do not repeat completed actions. Do not start
STEP-002 (builds, four-device probes) without the owner's explicit go-ahead.

STEP-000/STEP-001 are now COMPLETE except per-card PCIe telemetry, which Windows cannot
supply. CHECK-100 is PASS; CHECK-101 stays PARTIAL on PCIe alone. Read section 5a for the
now-evidence-backed route question and do not pick a route without the owner.
```

(Rewritten by Session 7, which satisfied the resume check. The old prompt said the resume check
was the reason for a new session; it is done.)

-

## 2. Where the work actually stands

| Gate | Status | Note |
|---|---|---|
| CHECK-100 | **PASS** **[Session 7]** | 11/11 CPU-only runner/lock/tool-loop cases PASS (re-verified). **Fresh-session resume: PASS** — Session 7 was a genuine post-reset session that resumed from files only. Receipt: `receipts/session7-resume.json`. |
| CHECK-101 | **PARTIAL** | Runtime identities + hashes closed. **Source-pin reconciliation now CLOSED [Session 7].** Only **PCIe telemetry** remains open, and it is UNKNOWN because Windows cannot supply it. |
| CHECK-102 … CHECK-108 | **NOT_RUN** | Untouched. STEP-002 and later. |

Only CHECK-100 was promoted, and only on new evidence. Do not promote anything else without it.

-

## 3. THE ONE THING TO UNDERSTAND FIRST: the route divergence

`PLAN.md` routes this work to **Strata's own `strata-dsv41` engine** built with Windows SYCL.
`PLAN.md:32` explicitly supersedes llama.cpp for this route. `PLAN.md:252` fences off the first
session: *"do not start a 257 GB download, GPU workload, production service change."*

A prior session (recorded honestly in `FINDINGS.md` as "SESSION 3 — ROUTE DIVERGENCE") did the
work in a **llama.cpp SYCL fork at `C:\llamacpp-v41`** instead, and crossed all three of those
boundaries. The production change was **rolled back and SHA256-verified**. The divergence is
recorded, not hidden.

That session also **disproved the premise** the Strata route was justified by. `TASK-STATE.json`
had claimed 1017 "cannot run in the llama.cpp fork at all" and that "~510B at ~2.7bpw is ~170GB >
128GB VRAM". Both are false by measurement: llama.cpp has a `deepseek41` architecture, the pack
loads and generates on 4× B70 (exit 0), and the measured set is **128.74 GiB at 2.0625 bpw**,
which fits in 4×32 GB with `-ngl 38` plus ~8.5 GiB host-staged weights.

**This is a decision input, not a decision.** Whether to amend the plan toward llama.cpp or stay
on Strata is the owner's call. Do not silently re-route a second time.

-

## 4. What is closed (do not redo)

- **Runtime identities (CHECK-101)**: icx `2026.0.0.20260331`; `ze_loader.dll` `1.32.0`;
  `ur_loader` `0.12.0`/`0.11.10`; `sycl9.dll` `2026.0.0.0` (2025.1 ships `sycl8`); GPU driver
  `32.0.101.8976`; L0 device `1.15.39183+4`, ext `20.2.0`; four B70s = 4× `level_zero:gpu`.
- **Hashes**: `ze_loader` `BC43DC7C…5172`, `ur_loader` `CA884A22…C071C5`,
  `mkl_rt.2` `698C867E…E806` (MKL `20250100`), `mkl_rt.3` `6A312EB1…27D8` (MKL `20260000`).
- **Provenance**: strata tree HEAD `1c360526bce659f45cec60b2e36c46b7770c5bf1`, branch `win-port`,
  2026-10-16; `origin` = hotschmoe/Strata, `upstream` = Niko1221/Strata.
- **RAM reconciliation**: 6×16 GiB = 95.87 GiB usable. "128 GB" is board capacity, not installed.

Receipts are in `work/strata-v41-agent-runner/receipts/` with SHA256s recorded in
`machine-manifest.json`.

-

## 5. What is genuinely still open

1. ~~**CHECK-100 fresh-session resume**~~ — **[Session 7] PASS.** See `receipts/session7-resume.json`.
2. **PCIe negotiated width/generation** — still **UNKNOWN**. Both `dxdiag /t` and the
   `DEVPKEY_PciDevice_*` properties came up empty or ambiguous (all four cards report
   `Max == Current == 1`, implausible for B70). **[Session 7]** The Intel Arc Control fallback
   named here is **closed too**: Arc Control is not installed on GPU-BOX (no `Intel Arc Control`
   directory, no `igcl*.dll` in System32). Remaining option is an empirical host↔device bandwidth
   measurement sized to distinguish x1 from x8/x16. Do not write x16, and do not write x1.
3. ~~**`v0.2.6` pin comparison** — needs a fetch.~~ **[Session 7] CLOSED.** See §5a.
4. **18 real modifications** are captured, proven replayable (§6a), and **not** superseded by
   v0.2.6 — none of the six Windows-port markers exist there. Porting or upstreaming them is
   still open work and is now the concrete next step in either route.

### 5a. [Session 7] The route question is now evidence-backed

`git fetch origin --tags` settled the pin:

| Fact | Value |
|---|---|
| `v0.2.6` tag object | `ff91dd77a13857ccc2f1bd67edc9a8ecd4ecdfa4` (annotated; tag commit adds docs only) |
| Peeled code commit | `4b9e05a2a806a3fe24f7b2560d98626c37dade35` |
| Remote carrying it | **`upstream`** (Niko1221). `origin` has **0** matching refs. |
| Relation to deployed HEAD | Not an ancestor either way. **2022 commits ahead** of `origin/main`. |
| Deployed HEAD relation | `win-port` = `origin/main` + **26** commits, **0 behind**. |

**The decisive measurement:** the deployed tree has **0** `dsv41` files. `v0.2.6` has **132** —
`docs/DEEPSEEK41.md`, `data/dsv41/profile-2.00.bin`, `include/strata/dsv41/*` — and its own doc
says *"Strata runs it with its own engine, `strata-dsv41` (`src/dsv41`, ported from Project Maya's
`maya-ds4`)"*. So the engine PLAN.md routes to **exists upstream and does not exist in the
deployed tree.** The plan's premise holds.

The three options, for the owner — not for the agent to pick:

- **A. Stay on Strata** — check out v0.2.6 into a *separate* directory (not `strata-win`), re-apply
  or upstream the 18 Windows fixes, build `strata-dsv41` with Windows SYCL. Largest effort; the
  engine is actually there.
- **B. Amend toward llama.cpp** — session-3 measurements stand (128.74 GiB @ 2.0625 bpw, loads and
  generates on 4× B70). Needs an explicit PLAN.md amendment. Do not re-route silently.
- **C. Upstream the 18 Windows fixes** — route-independent, helps A and B. Lowest risk.

Nothing was checked out or merged in Session 7; the pin work was `git show` / `ls-tree` on the
existing object store only.

-

## 6. HARD WARNINGS — read before any command in `strata-win`

**`rescue/working-tree.patch` DOES NOT EXIST *in the Windows tree*.** There is no `rescue/`
directory under `%USERPROFILE%\strata-win`. A prior note claimed such a file was the only
backup of the uncommitted work and forbade resets on that basis; that claim was false.

**[Session 7]** A real patch *does* exist — in this repo, at
`work/strata-v41-agent-runner/rescue/working-tree.patch` (20,189 B, 18 files). It is a valid
restore artifact, see §6a. The rule still stands for other reasons: do not reset until you have
confirmed the backup in §7 verifies.

**Never run in `%USERPROFILE%\strata-win`:** `git reset --hard`, `git stash -u`, `git clean -fd`,
or a branch switch — until you have personally confirmed a current backup exists.

**The "3043 modified files" is mostly fake.** `git diff --stat` shows 3043 files / 824,758 ins /
824,624 del — the symmetric CRLF signature. `core.autocrlf` is unset. The real change set is:

```
git diff --ignore-cr-at-eol --stat   ->   18 files, 157 insertions, 23 deletions
```

Always use `--ignore-cr-at-eol` for diff review or patch export, or the 18 real files are invisible
inside 3043 phantom ones.

-

## 6a. [Session 7] Restore procedure — proven

```
# 1. Verify the backup first
ls -la /mnt/d/backups/strata-win-20261027-131251/
cd /mnt/d/backups/strata-win-20261027-131251/ && sha256sum -c SHA256SUMS   # 4/4 OK, ~28 s

# 2a. Full restore (authoritative, includes .git and untracked)
tar xf strata-win-full.tar          # 17,250 entries, 116 .git/ entries, real pack files

# 2b. Or targeted restore of just the 18 changes onto a clean checkout
git show HEAD:<file> > /tmp/clean/<file>     # for the 18 files below
cd /tmp/clean && git init -q . && git apply <patch>
tar xzf untracked-files.tar.gz -C <dest>     # REQUIRED: carries sycl/include/strata_win_undefs.h
```

The 18 files (do not drive this loop from `git diff --name-only`, see §6):

```
sycl/CMakeLists.txt
sycl/include/dpct/device.hpp
sycl/include/dpct/kernel.hpp
sycl/include/dpct/memory.hpp
sycl/include/strata/core/ep_mem.hpp
sycl/src/core/copy_queue.cpp
sycl/src/core/device.dp.cpp
sycl/src/core/expert_source.cpp
sycl/src/core/gguf_expert_source.cpp
sycl/src/core/pinned.dp.cpp
sycl/src/kernels/cuda/verify_kernels.dp.cpp
sycl/src/kernels/iq_multi_parity.cpp
sycl/src/kernels/kv_hybrid_parity.cpp
sycl/src/kernels/qsa_prompt_attn_parity.cpp
sycl/src/kernels/rope_parity.cpp
sycl/src/kernels/sampler_parity.cpp
sycl/src/platform/direct_file.cpp
sycl/src/program/generate.cpp
```

## 7. Backup

Taken 2026-10-27 to `D:\backups\strata-win-20261027-131251\` containing:
`HEAD.txt`, `branch.txt`, `head-log.txt`, `remotes.txt`, `status-porcelain.txt`,
`working-tree-real.patch` (CR-insensitive), `working-tree-raw.patch` (full fidelity),
`untracked-files.tar.gz`, `strata-win-full.tar`, `SHA256SUMS`.

**Status: taken and verified.** `strata-win-full.tar` = 2,110,720,000 B, 17,250 entries, 116 `.git/`
entries, SHA256 `b9d01054...783c`. This is the restorable artifact.

**[Session 7] CORRECTION — the `.patch` files DO re-apply cleanly. L-034 was wrong.**

L-034 claimed both patches fail `git apply --check` and that restore must come from the tar. The
earlier test ran `git apply --check` **forward, in place, inside the already-modified worktree** —
which must fail, because the change is already applied there. The same session's *reverse* check
passing was the tell.

Correct test — export the pre-image from `HEAD` into a clean directory, then apply:

```
git show HEAD:<file> > /tmp/clean/<file>      # 18 files; HEAD blobs contain zero CR bytes
cd /tmp/clean && git init -q . && git apply <patch>
```

| Patch | `--check` on clean HEAD | Applied vs live worktree |
|---|---|---|
| `working-tree-real.patch` (backup, 20,225 B) | exit 0 | **18/18 byte-identical** |
| `rescue/working-tree.patch` (repo, 20,189 B) | exit 0 | **18/18 byte-identical** |
| `working-tree-raw.patch` (backup, 75.8 MB) | covers all 3043 files | full-fidelity pre-image |

The two 18-file patches differ only in `index`-line abbreviation length; content is identical.
So there are three good restore paths, not one.

**The one caveat that is still true:** the patches reference `sycl/include/strata_win_undefs.h`,
which is **untracked**. A patch restore gives you the 18 modified files but *not* that header. It
is in `untracked-files.tar.gz` and in the full tar. Restore = patch + `untracked-files.tar.gz`,
or the full tar alone.

**Landmine — `--name-only` vs `--stat` disagree by 3000+ files.** `git diff --ignore-cr-at-eol
--name-only` lists **3043** files; `--ignore-cr-at-eol --stat` reports **18**. A loop driven from
`--name-only` walks the whole tree and looks exactly like a hang. Use `--numstat`, or the explicit
18-file list in §6a.

**Verify it before trusting it** — the job took ~10 min and the patches are large:

```bash
ls -la /mnt/d/backups/strata-win-20261027-131251/
cd /mnt/d/backups/strata-win-20261027-131251/ && sha256sum -c SHA256SUMS
```

If `sha256sum -c` fails or files are missing/0-byte, **retake the backup before touching the tree.**

-

## 8. Host access notes (learned painfully)

- `ssh gpu-box` lands in **WSL2 bash**. Windows facts must come from `powershell.exe` / `cmd.exe`;
  WSL output is not Windows evidence.
- For anything with spaces in the path (`C:\Program Files (x86)\…`), or with `$` variables, **stage a
  `.bat` or `.ps1` file and call it**. Inline quoting and inline `awk`/`$C` broke repeatedly.
- `sycl-ls` **without** the oneAPI env reports OpenCL only — no `level_zero` lines. Run it after
  `setvars.bat --force` to see the four L0 devices. Probe without env silently under-reports.
- `ONEAPI_DEVICE_SELECTOR` and `SYCL_DEVICE_FILTER` must stay **empty**. Setting either silently
  kills `llama_context` construction.
- `tasklist | grep -c llama-cli` gives **false positives**. Use
  `tasklist /fi "IMAGENAME eq llama-cli.exe" | grep -c 'llama-cli.exe'`.
- Do not judge liveness by log size — redirected stdout is block-buffered. Use VRAM delta.
- Windows PowerShell 5.1 / .NET 4.0 only. No ternary operators.

-

## 9. Production state — verify, do not assume

llama-swap on GPU-BOX was modified in session 3 and **rolled back**. As of 2026-10-27 12:36 CDT:

- config `C:\llama-swap\config.windows.yaml` SHA256 = `38A827771DEE609C442CCE106331C9466C4469547B9C3D7C57AACD3CA579ECDA`
  (byte-identical to pristine backup `config.windows.yaml.bak-v41flash-20261027-114305`)
- `v41` references in config: **0**
- `/v1/models` → **9 models**, none of them v41
- llama-swap service: `Running`

**llama-swap binds to the Tailscale address `<gpu-host-ip>:8080`, NOT localhost.** Probing
`127.0.0.1:8080` returns empty and looks like an outage. Use the Tailscale IP.

-

## 10. GPU health as of handoff (relevant if anyone proposes a reboot)

| Signal | Result |
|---|---|
| uptime | ~50 h (boot 2026-10-25 11:08:30) |
| **TDR / Event 4101 (7d)** | **ZERO** |
| GPU/display device errors (7d) | none |
| WHEA Id 22 | 8 in 7d, but one per boot at ~23 s; none at runtime |
| Kernel-Power 41 | 2 pairs, both 2026-10-24, before this boot |
| VRAM free | 32520 / 32540 / 32541 / 32373 of 32558 MiB |

The prior session's crashes were **user-mode process exits** (`-1` at `llama_context`
construction), not driver-level GPU faults. A reboot was **not** indicated on this evidence. If a
STEP-002 device probe hangs or a card drops off, revisit that.

**Note**: llama-swap's log had accumulated ~1.2 MB of `:9063`/`:9024` proxy errors from the
experimental v41 server. Harmless but noisy. Rotation was offered and not performed.

-

## 11. Git state at handoff

Branch `work/strata-v41-agent-runner`, remote `Captain-Tripps/b70-lab`. Recent commits:

- `1022337` — record session-3 route divergence, correct false premise, note rollback
- `ff5c684` — close CHECK-101 runtime identities with read-only receipts
- `0137936` — capture oneMKL + deployed binary hashes for STEP-001
- `9a31603` — pin source provenance, correct crisis-worthy notes, record GPU health

Untracked local backups (`*.bak-*`) are deliberately **not** committed.

**[Session 7]** The `win-port` branch has **no upstream configured** (`git rev-parse @{u}` fails).
`1c360526` is published on origin only as `refs/heads/b70-night-20261016`. There is no
`origin/win-port`. Remote branches on origin: `b70-night-20261016`, `main`,
`ple-prefetch-keymatch-s54`, `pr/sycl-*`.
