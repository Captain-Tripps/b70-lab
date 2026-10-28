# 1017 sizing + the `-ts` split-boundary finding (2026-10-27 22:05)

Follow-up to `PREFILL-INVESTIGATION.md`. Two useful results: **the "smaller quant" option does not
exist**, and there is a **specific, documented split-boundary trap** that plausibly explains the
slow prefill on a 4-card layer split.

-

## 1. There is no smaller 1017 quant that helps

Checked the alternatives on HuggingFace.

| Pack | Size | Verdict |
|---|---:|---|
| **ours**: ISTA-DASLab IQ2_XXS GSQ-RCO | 138.2 GB (128.74 GiB) backbone + 110 GB engram | the smallest sane one |
| `cliecy/...-V3-IQ1S` | **224 GB** | author's own verdict: *"fail: quantization alone costs this much"* (KLD 0.446, top-1 77.8%) |
| `cliecy/...-UD-IQ2XS` | **158 GiB on GPU + 103 GiB engram in RAM**, 281 GB disk | designed for 2x96 GB NVIDIA; needs **115 GiB free RAM** |

So the "download a smaller quant so it fits alongside production" plan (my option B) is **dead**:
every alternative is equal or larger, and the 1-bit one is measured as badly degraded.

**Our pack is already at the practical floor.** It fits 4x B70 only because `-ngl 38` leaves 3 of 41
layers on CPU (ledger L-012: 131,187 MiB wanted vs 130,232 available).

## 2. The real find: the compressed-KV split boundary

From the UD-IQ2XS model card, verbatim:

> V4.1 compresses its KV cache on a few source layers (2, 8, 14, 20), and the layers after each
> source read the source's rows. With the default two-GPU split, the boundary lands at layer 21.
> Layer 20's compressed KV then sits on GPU 0 while its 19 readers sit on GPU 1, and **every
> generated token copies the whole compressed cache through the host. That was about 340 MB per
> token in each direction at 16K context**, and it grows with the context. `-ts 48,52` puts the
> boundary at layer 20 instead. On Q2_K this took generation at 16K **from 23 to 34 tok/s**.

### Why this matters on our box specifically

Our 1017 runs used **no `-ts` at all** — llama.cpp then splits 41 layers evenly across 4 cards,
putting boundaries at ~10.25, ~20.5, ~30.75.

**The boundary at 20.5 lands exactly where the model card says it must not:** source layer 20 on
one card, its readers (21-40) on the next. That is the pathological case, and we hit it **twice**
over (a second boundary at 30.75 also sits inside layer 20's reader set).

At 16K context that is ~340 MB copied per token **per crossing**, over a ~12 GB/s PCIe path. That
alone could account for a large share of the prefill and decode slowness — and it is a *config*
bug, not a kernel bug.

### The constraint on fixing it

Source layers and their readers: 2→(3-7), 8→(9-13), 14→(15-19), **20→(21-40)**.

Keeping every source with its readers means one card holds layers 20-40 = **21 of 41 layers**,
which cannot fit in 32 GB. So a 4-card split **cannot** avoid all crossings. The best available
choices put boundaries at 19|20, 13|14, or 7|8, accepting one paid crossing (source 20) instead of
three.

**Candidate splits to test** (41 layers, 4 cards):
- `-ts` that ends cards at 19, 13, 7 → boundaries 7|8, 13|14, 19|20 — all "clean", but lopsided
- Weight-balanced alternative: keep 19|20 clean and accept a split inside 21-40, which costs nothing
  extra because those layers are all readers of the same source.

That second one is the promising shape: **only the 20→21 crossing is expensive; boundaries inside
21-40 are free.** So a split like 8|6|6|21 is ideal semantically but impossible in VRAM; the
practical best is to move as much as fits after layer 20 and keep 19/20 together.

## 3. Two more transferable tricks from that card

- **`-ot "engram_embd.weight=CPU"`** — pin the engram table to CPU explicitly. Our pack ships engram
  as a separate 110 GB GGUF; the same idea applies.
- **`LOW_RAM=1` equivalent** — keep engram rows on disk and read on demand: ~10 GiB RAM instead of
  ~115 GiB. **This is the direct fix for the host-RAM thrash** that made my earlier runs fail
  (1.3 GB free of 95.9 GB). We have 95.9 GB total, so a 110 GB engram table cannot be resident
  anyway — it must be streamed. Worth checking whether our `-lm none` was forcing it into RAM.
- **Chat template**: the GGUF's embedded template is the **V4** one; V4.1 needs different tool-call
  tag names. Explains odd tool behaviour if we ever serve it.

## 4. Revised recommendation

Option B (smaller quant) is **not viable** — §1. That leaves:

- **A. Maintenance window** to free the ~58 GB llama-swap holds, then test `-ts` variants. This is
  now higher-value than before, because §2 gives a specific, testable, documented hypothesis rather
  than a guess.
- **C. Out of scope on this box** — if the only acceptable config is a maintenance window, that is a
  product decision, not an engineering one.

**The single highest-value experiment** is now: load once with a `-ts` that keeps 19|20 together,
and compare pp/tg against the default split. That requires the VRAM, so it requires option A.

Unevaluated alternative: our current pack already runs at `-ngl 38` with 3 layers on CPU. A `-ts`
change alone does not need more VRAM, so it could be tested **if** production were briefly stopped —
same requirement.

## 5. Correction to my earlier framing

I told the owner "the blocker is VRAM capacity." That is true but incomplete. The more accurate
statement is:

> The pack barely fits (955 MiB deficit at `-ngl 99`), and on top of that our split boundaries sit
> exactly on the model's compressed-KV sources, which the upstream quant author measured as costing
> ~340 MB per token per crossing. Both problems are fixable; neither is a kernel bug.

## 6. Not established

- No prefill measurement. Still blocked on VRAM.
- The `-ts` hypothesis is **documented upstream for 2-GPU NVIDIA**, not measured on 4x Arc. It is a
  strong lead, not a result.
- Whether our engram handling currently forces the 110 GB table into RAM (would explain the thrash).
