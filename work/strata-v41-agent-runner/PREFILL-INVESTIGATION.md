# Prefill investigation — session findings (2026-10-27 22:00)

Goal: fix 1017 prefill (pp 0.33 t/s vs tg 3.05 t/s).

**Outcome: the original diagnosis was already fixed by an earlier session; the blocker is now
VRAM capacity/contention, not HC fusion.** No prefill number was produced.

-

## 1. The HC-fusion hypothesis is ALREADY FIXED — do not chase it

The plan was "HC fusion is disabled -> batched prompt path dies -> pp collapses to per-token".
A prior session patched `src/llama-context.cpp` `resolve_fused_ops()` for exactly this
(`llama-context.cpp.orig-fusedprobe` is the backup), and **it works**:

```
I resolve_fused_ops: resolving fused DeepSeek V4 HC support:
I resolve_fused_ops: fused DeepSeek V4 HC pre enabled
I resolve_fused_ops: fused DeepSeek V4 HC comb enabled
I resolve_fused_ops: fused DeepSeek V4 HC post enabled
```

That is from the 12:19 run *and* from tonight's attempt. The old warning
`fused DeepSeek V4 HC pre not supported, set to disabled` is **gone**.

So the 0.33 t/s figure predates the fix, or has another cause. **The HC work is done.**

## 2. What actually blocks loading now

Tonight's run died with a precise, different error:

```
E ggml_backend_buft_alloc_buffer_n_default: failed to allocate SYCL1 buffer of size 6898683648
E llama_model_load: error loading model: unable to allocate SYCL1 buffer
```

6.9 GB could not be allocated on card 1. Measured VRAM at the time:

| Card | Used |
|---|---:|
| card 0 | 20.81 GB |
| card 1 | 18.18 GB |
| card 2 | 19.20 GB |
| card 3 | 0.16 GB |

**~58 GB was already occupied by `llama-swap`** (production, 9.3 h uptime). The pack needs the
whole 4-card budget; `FINDINGS.md` L-012 already measured this ceiling:

```
GPU total = 131,187 MiB requested vs 130,232 MiB physical (4 x 32,558)
```

**The pack already does not fit, with 955 MiB of headroom deficit — and llama-swap takes 58 GB of
it.** There is no configuration in which 1017 loads while production is resident.

## 3. Two hard constraints, both independent of tuning

1. **The pack exceeds total VRAM by ~955 MiB** even on an idle box (L-012). Any run needs
   `-ngl 38` (3 layers on CPU) to fit at all — that is why the working config uses `-ngl 38`,
   not `-ngl 99`.
2. **Production holds 58 GB.** So 1017 cannot load concurrently with llama-swap.

## 4. What this means for the prefill question

I cannot answer "is prefill fixed?" tonight without a load that succeeds, and a load that succeeds
requires ~58 GB of production VRAM to be released. That is a production action and I will not take
it unilaterally.

The one piece of evidence I do have: the 12:19 server run **loaded, enabled all three fused HC ops,
listened on 9063, and served 3 requests**. It did not crash at prefill. That is weak but positive
evidence that the fusion patch improved things — and it directly contradicts "prompt processing
crashes" from L-020/L-021.

## 5. Blocked on a decision

To make progress I need one of:

- **A. A maintenance window**: pause llama-swap, run the test, restart it. Requires owner go-ahead —
  it is production, serving 9 models.
- **B. A smaller 1017 quant** (single shard, IQ1/IQ2) that fits in the ~70 GB left after production.
  No production impact. This is the low-risk option and it also removes the RAM-thrashing confound
  from the earlier night's work.
- **C. Accept 1017 needs a 5th card or a bigger-VRAM card**; treat it as out of scope for this box.

**Recommendation: B.** It answers the prefill question without touching production, and it avoids
the host-RAM thrash that produced tonight's earlier false starts.

## 6. What was NOT established

- No pp/tg measurement at any batch size. Both llama-bench and llama-cli attempts failed, for the
  reasons below.
- Whether the 0.33 t/s figure is now obsolete after the fusion fix. **Plausible, unproven.**

## 7. Tooling failures that cost the evening (all mine, all avoidable)

| Failure | Cause | Fix |
|---|---|---|
| `llama-bench` exits immediately, 0 bytes | no `setvars.bat` in the script → `EXIT=-1073740612` (0xC00004BC, DLL load failure) | always `call setvars.bat` first |
| Script does nothing at all | `.cmd` written with LF endings; `cmd.exe` mis-parses | write CRLF (`sed 's/$/\r/'`) |
| Zero output from a running binary | piped through `findstr`/`grep` — buffers until exit | redirect straight to a file |
| `-fit` rejected | `-fit` is a `llama-cli` flag, not a `llama-bench` one | drop it for bench |
| Long exec dies mid-run | harness SIGKILLs the exec, which kills the ssh channel and the remote child | use `exec(background=true)` |
| Bench reported "finished" while alive | `Get-Process llama-bench` silently returns nothing (PowerShell eats `-bench`) | `Get-Process -Name 'llama-bench'` or `tasklist /FI` |
| PowerShell vars became `/bin/bash` | `$_` expanded locally inside ssh double quotes | pipe a script via `base64`/`-EncodedCommand` (UTF-16LE) |
| `-EncodedCommand` garbled | fed UTF-8 | `iconv -f UTF-8 -t UTF-16LE` first |
| **Destroyed the W-014 success log** | `st10.bat` starts with `del /q ... st10.log`; I ran it without copying first | copy logs before re-running a script that self-deletes |
| Host RAM exhausted mid-load (1.3 GB free) | 128.74 GiB pack on a 95.9 GB box | smaller quant, or a RAM guard |

## 8. State at handoff

| Item | Value |
|---|---|
| llama-cli / llama-bench | none running |
| llama-server | one instance (19948), not serving 1017 |
| llama-swap | running, production, ~58 GB VRAM held |
| Free RAM | 85.2 GB |
| st10.log | **overwritten by me**; the 08:56 known-good content is lost |
| Build | `de5122d` + 3 uncommitted patches (fused-ops fix among them), `llama.dll` rebuilt 10:50 |
