# DSA scoring and selection: upside ceiling from existing data — 2026-11-13

## Decision

Park a new DSA scorer or selection kernel (L2 score variants, L5 indexer XMX) for the production MTP workload. The
existing measurements bound the whole depth-related decode cost below the handoff's 8% deep-workload gate, and
scoring and selection are only part of that cost. No new measurement was taken for this note. Reopen only with
a workload where target-only decode at depth is the declared target, or with new evidence of a larger depth cost.

## Inputs

All numbers come from the [attention depth screen](../2026-11-12-attention-depth/): promoted executable
`f89820fe92e4…`, split `14,25,36`, 128 greedy tokens, one prompt family, prefixes of 2048 and 100000 tokens.

| Measure | 2k | 100k | Gap | Gap as share of 100k |
|---|---:|---:|---:|---:|
| MTP decode, three unprofiled runs each | 23.06 ms/token | 24.30 ms/token | 1.24 ms | 5.1% |
| Target-only decode, one run each | 37.06 ms/token | 40.84 ms/token | 3.78 ms | 9.3% |
| CUDA0 `dsa_score` + `dsa_select`, profiled, target-only | 0.191 ms | 1.256 ms | 1.065 ms | not a wall-time share |

## Reasoning

1. The handoff's L2 gate is at least 3% geometric-mean decode gain, or at least 8% on a declared deep-context
   workload. A depth-specific kernel helps mainly at depth, so the 8% gate is the relevant one.
2. Under MTP, the live mode, the entire 2k-to-100k decode gap is 1.24 ms/token, 5.1% of the 100k time. Removing
   every depth-related cost, scoring, selection and anything else, would not reach 8% on this measure.
3. That gap is not a hard bound. The 100k runs accepted 118/126 drafts and the 2k runs 110/126, so higher
   acceptance at depth may hide some depth cost. Target-only removes that confound: there the gap is 9.3%, from
   one run per depth.
4. Scoring and selection are part of the target-only gap, not all of it. On CUDA0 their profiled increase is
   1.065 ms per stream token against a 3.78 ms wall gap. The depth record warns that stream intervals include
   gaps and are not additive across cards, so this note does not convert them into a wall-time share.
5. Combining 3 and 4: even in target-only, a scorer would need to remove most of the depth cost to clear 8%.
   Under MTP the reachable gain is smaller still. The earlier sx2b4 screen fits this: +2.58% on one 103k MTP pair.

## Limits

- One prompt family, 128 generated tokens, and single target-only runs. A wider corpus could show a larger gap.
- Depth beyond 100k (up to 131072) was not measured. The gap may grow there.
- Depth-independent scoring cost is small at 2k (0.191 ms on CUDA0) and does not change the conclusion.

## Next action

Spend the next effort on L3 (incremental prompt preparation) and L4 (checkpoint spacing). Both target first-token
latency on long agent turns. A fresh 115,116-token prompt took 102.85 s to first token in the
[trim-crash record](../2026-11-11-trim-crash/).
