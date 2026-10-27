# Session handoff — strata-v41 agent runner

Written 2026-10-27 ~13:20 CDT at the end of a long working session, to be read by a **fresh**
agent session. Read this before touching anything.

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

The single acceptance test this fresh session exists to satisfy: CHECK-100's fresh-session
resume. Record whether this session satisfies it - it is the reason you are a new session.
```

-

## 2. Where the work actually stands

| Gate | Status | Note |
|---|---|---|
| CHECK-100 | **PARTIAL** | 11/11 CPU-only runner/lock/tool-loop cases PASS. **Fresh-session resume: NOT_RUN** — that is this session's job. |
| CHECK-101 | **PARTIAL** | Runtime identities + hashes closed with receipts. **PCIe telemetry and source-pin reconciliation still open.** |
| CHECK-102 … CHECK-108 | **NOT_RUN** | Untouched. STEP-002 and later. |

Nothing was promoted to PASS. Do not promote anything without new evidence.

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

1. **CHECK-100 fresh-session resume** — needs *this* new session. That is the point of the handoff.
2. **PCIe negotiated width/generation** — Windows cannot supply it. Both `dxdiag /t` and the
   `DEVPKEY_PciDevice_*` properties came up empty or ambiguous (all four cards report
   `Max == Current == 1`, which is implausible for B70). Closing it needs Intel Arc Control, or an
   empirical host↔device bandwidth measurement sized to distinguish x1 from x8/x16.
   Recorded as **UNKNOWN** — do not write x16, and do not write x1.
3. **`v0.2.6` pin comparison** — needs `git fetch origin` in the strata tree and a decision about
   which remote carries the tag.
4. **18 real modifications** in the strata tree are captured in the backup but not yet ported or
   reconciled against the pinned base.

-

## 6. HARD WARNINGS — read before any command in `strata-win`

**`rescue/working-tree.patch` DOES NOT EXIST.** A prior note claimed it was the only backup of the
tree's uncommitted work and forbade resets on that basis. Verified false: no `rescue/` directory,
no patch file. Treat the tree as **unbacked** unless the backup described in §7 is present.

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

## 7. Backup

Taken 2026-10-27 to `D:\backups\strata-win-20261027-131251\` containing:
`HEAD.txt`, `branch.txt`, `head-log.txt`, `remotes.txt`, `status-porcelain.txt`,
`working-tree-real.patch` (CR-insensitive), `working-tree-raw.patch` (full fidelity),
`untracked-files.tar.gz`, `strata-win-full.tar`, `SHA256SUMS`.

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
