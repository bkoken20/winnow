# Does a second extraction pass pay for itself?

**Yes — but not the second pass I expected, and for a different reason.** Running the text
twice at two *small* chunk sizes raises coverage by 25–32 points. Adding a whole-document
pass, which was the original idea, adds about 3 and loses outright to simply using smaller
chunks for the same money.

Reproduce with `two_pass_study.py`, which needs source paths in the environment and
`chunk_size_study.py` to have run first — see [README.md](README.md).

## The hypothesis being tested

The chunk-size studies left this open: small chunks recover far more detail, yet the large
settings still found claims the small ones missed. Those looked like document-level
synthesis — claims that can only exist when the model sees the whole text. If so, a small
pass plus one whole-document pass should beat either alone.

## Method

Same as `CHUNK_SIZE.md`: `qwen2.5:14b-instruct` at temperature 0, `nomic-embed-text` for
similarity, near-duplicates collapsed at cosine ≥ 0.93 (threshold fixed in advance), and
**claim correctness not measured**. A merge is deterministic given both passes' outputs, so
once each pass has been run once every combination is computed offline at no further cost.

## Part A — written documentation (3 docs, ~150 KB, union of 635 claims)

| approach | claims | coverage | seconds |
|---|---:|---:|---:|
| 2,000 alone | 275 | 44% | 836 |
| 1,000 alone | 337 | 53% | 1060 |
| 4,000 alone | 192 | 31% | 609 |
| 120,000 alone | 24 | 4% | 135 |
| **2,000 + 120,000** *(the hypothesis)* | 292 | **47%** | 971 |
| **1,000 + 2,000** | 494 | **78%** | 1896 |
| 1,000 + 4,000 | 461 | 73% | 1670 |
| 2,000 + 4,000 | 377 | 59% | 1445 |

## Part B — spoken transcript (21 KB, own union of 77 claims)

**These are a fresh extraction, not the one in `CHUNK_SIZE.md`.** That study saved summary
rows but not the claim texts, so this one had to re-run the transcript at every size to have
texts to merge. Same model, same temperature, same transcript — and the 1,000-character
setting returned 30 claims here against 28 there, moving the union from 76 to 77 and that
setting from 37% to 39%. Both runs are reported as measured; neither is a correction of the
other. Extraction at temperature 0 is repeatable, not identical.

| approach | claims | coverage | seconds |
|---|---:|---:|---:|
| 2,000 alone | 29 | 39% | 101 |
| 1,000 alone | 30 | 39% | 104 |
| 40,000 alone (whole) | 7 | 9% | 30 |
| **2,000 + 40,000** *(the hypothesis)* | 35 | **47%** | 131 |
| **1,000 + 2,000** | 55 | **71%** | 205 |

## The result

**The hypothesis loses at matched cost.** On documentation, 2,000 + whole-document costs
971s for 47%. Simply running 1,000 alone costs 1060s for 53%. Paying for a whole-document
pass buys less than spending the same time on a finer single pass.

**But two small passes win decisively.** 1,000 + 2,000 reaches 78% against 53% for the best
single pass, and on speech 71% against 39% — a bigger jump than any single-setting change
measured anywhere in these studies.

**The mechanism is boundary diversity, not synthesis.** Different chunk sizes cut the text
at different points, so each pass puts different sentences next to each other and surfaces
different claims. Nothing about seeing the whole document is required, or even helpful.

**Where the hypothesis was right:** 17 of the whole-document pass's 24 claims were unique to
it, and they are recognisably a different kind of claim — the architectural generalisations:

> Flash Attention reduces the memory requirements for self-attention layers from quadratic
> to linear with respect to the number of input tokens.
>
> Grouped-Query-Attention allows for less drastic reduction in the number of key-value
> projection weights compared to MQA, preserving more model capacity.

So a whole-document pass does contribute a distinct *character* of claim. It contributes 17
of them against a union of 635. Right in kind, negligible in volume.

## What changed in the tool

Extraction now takes a list of chunk sizes. The second pass is **on for `ingest` and off for
`index`**, because the cost asymmetry is stark: judging one 25-minute talk costs 205s instead
of 101s, while indexing the 7.5 MB corpus below costs 26 hours instead of 12.
Both are configurable (`ingest_extra_passes`, `index_extra_passes`; an empty list disables).

Two passes over one text produce genuine rewordings of the same assertion — 19% of the
merged set — so claims closer than `duplicate_threshold` (0.93) to something already in the
corpus are no longer stored. Without that, a corpus fills with echoes of itself and later
novelty verdicts read `known` for the wrong reason entirely.

## The caveat that governs every number here

Coverage is measured against the union of what the tested settings found between them. It is
**not** a percentage of what exists, and it systematically flatters whichever set of settings
happened to be tested: every new setting enlarges the union and pushes every existing
figure down.

This is not hypothetical. The 4,000-character setting has been reported at **70%**, then
**31%**, then **31%** across three studies — the same run, three different denominators, as
smaller chunk sizes and second passes kept revealing claims nothing had previously looked
for. A third pass would very likely do it again.

Read these tables as comparisons *within* one study. Never quote a coverage figure from one
against a figure from another.

## Open

- **A third pass is untested.** Given that the second one gained 25–32 points, the returns
  have plainly not been exhausted, and the union itself would grow again.
- **Which pair is best is unmeasured beyond these sizes.** 1,000 + 2,000 was the best of the
  15 pairings tried, but 500 + 1,500, say, is unexplored.
- **Correctness remains unmeasured.** Everything here counts what was found, never whether
  it was true. A pass that doubles the claim count while halving their accuracy would look
  identical in these tables.

---

# Addendum: the third pass

Computed from the stored outputs of the study above — every pass's claim texts are
persisted, so all merges are deterministic and need no further extraction. Reproduce with
`third_pass_analysis.py`, which calls no model and needs only `two_pass_study.py` to have
run ([README.md](README.md)).

| passes | documentation coverage | minutes | transcript coverage | minutes |
|---|---:|---:|---:|---:|
| 2,000 | 44% | 13.9 | 39% | 1.7 |
| 1,000 + 2,000 | 78% | 31.6 | 71% | 3.4 |
| **1,000 + 2,000 + 4,000** | **90%** | 41.8 | **92%** | 4.5 |

The third pass gains **+12 points on documentation and +21 on speech**, and the returns have
still not flattened.

**What it costs depends entirely on the job**, and the asymmetry is severe:

| | 1 pass | 2 passes | 3 passes | third pass adds |
|---|---:|---:|---:|---:|
| ingest — one 25-minute talk | 1.7 min | 3.4 min | 4.5 min | **+66 seconds** |
| index — a 7.5 MB corpus | 11.6 h | 26.3 h | 34.8 h | **+8.5 hours** |

The ingest row is measured. The index row is projected from measured throughput
(0.142 / 0.180 / 0.246 KB/s at 1k / 2k / 4k) and is **not** a measured run.

So three passes are the default for `ingest`, where the third costs about a minute, and
indexing stays single-pass, where it would cost most of a working day. Both are configurable
(`ingest_extra_passes`, `index_extra_passes`).

**The usual caveat, and it bites harder here.** 90% and 92% are shares of the union of what
these settings found between them — not of what exists. A fourth pass would enlarge the union
again and push both figures down, exactly as 4,000 went 70% → 31% across earlier studies. The
honest statement is that three passes find substantially more than two, not that they find
90% of everything.

**Untested:** a fourth pass; whether pass sizes other than 1k/2k/4k do better.

**Partly answered since:** correctness. Hand-graded faithfulness is 88% on a 25-claim
sample (`CORRECTNESS.md`) with no fabrication observed -- the errors are dropped
qualifiers, not invention. But faithfulness *by chunk size* is still unmeasured, because
the automated judge could not detect the error class at all. **These multi-pass defaults
therefore still rest on volume evidence alone.**
