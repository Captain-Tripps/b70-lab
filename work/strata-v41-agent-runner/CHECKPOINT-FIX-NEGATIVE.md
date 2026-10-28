# 1017 checkpoint-fix test: NEGATIVE result (2026-10-28 00:55)

Tested `--cache-ram 0 --ctx-checkpoints 0` as the candidate fix for the crash-after-checkpoint
observed in `PREFILL-MEASURED.md`. **It does not fix it, and it makes the failure earlier.**

-

## 1. Result

| Run | Flags | Outcome |
|---|---|---|
| `srv-v41.bat` | checkpoints **on** (default) | reached `model loaded` + `listening`, served a request, processed 27 prompt tokens at **0.85 tok/s**, then `exit -1` right after `created context checkpoint 1 of 32` |
| `srv-nockpt.bat` | `--cache-ram 0 --ctx-checkpoints 0` | **never reached `model loaded`** — died at `llama_context` construction, `exit -1` |

Log: `C:\b70-work\srv-nockpt.log`, last real line:

```
I llama_context: n_ctx_seq (2048) < n_ctx_train (1048576) -- the full capacity of the model will not be used
==== srv-v41-nockpt exit -1 Wed 10/28/2026 0:55:20.35 ====
```

## 2. What this rules out

**Context checkpoints are not the cause of the load failure.** The config that *does* load has them
enabled; disabling them makes it fail sooner. So:

- The "crash after `create_check`" line in the earlier run is a **symptom of the shutdown path**, not
  the trigger. The process was already dying; the checkpoint write was simply the last thing it logged.
- L-021/L-022's candidate #2 ("`--cache-ram` / context checkpoints machinery") is **wrong** for the
  load failure.

## 3. What is still true

- **Prefill = 0.85 tok/s** (27 tokens in 31.75 s) — the only real number we have, 2.6x better than the
  ledger's 0.33.
- Fused HC pre/comb/post all report **enabled**.
- Batching engages: `graph (pp bs=512, tg bs=1): nodes = 4910 / 4844, splits = 166 / 13`.
- The pack needs `-ngl 38` (3 layers on CPU) to fit 4x32 GB at all.

## 4. Where the crash likely lives

Both variants die with `exit -1` and no error text, at different points:

- with checkpoints: after 27 prompt tokens, during generation setup
- without checkpoints: during `llama_context` construction

A silent `-1` at two different stages points at an **unhandled exception / abort in the deepseek41
SYCL path**, not a specific feature. The build has 3 uncommitted local patches
(`llama-context.cpp`, `llama-model-loader.cpp`, `deepseek41.cpp`) — the crash may be an interaction
between them.

**Next diagnostic that would actually discriminate:** run under a debugger or with
`GGML_SYCL_DEBUG=1` to get the abort site, rather than trying more flag permutations blind.

## 5. State

| Item | Value |
|---|---|
| llama-swap | **Running** (production restored) |
| 1017 processes | none |
| VRAM | all cards 0 GB |
| Free RAM | 84.8 GB |
| Scripts | `srv-v41.bat` (unmodified), `.bak-cp` backup, `srv-nockpt.bat` (test) |
