# How much text should go into one extraction call?

**Answer: far less than fits, and how much less depends on what the material is.** The
default is **2,000 characters**, down from ~120,000 (whatever the context window allowed).

Two studies, reproducible with `experiments/chunk_size_study.py` (4k and above) and
`experiments/chunk_size_small.py` (below 4k, plus a spoken-transcript check).

## The question

A 47 KB document fits entirely inside a 32k context window and yielded **6 claims**. That
looked like a model summarising rather than enumerating — but it could equally have been a
document with little in it. Counting claims cannot tell the difference, and neither can
counting them at two chunk sizes: smaller chunks mean more extraction calls, so more claims
appear whether or not they are worth having.

## Method

`qwen2.5:14b-instruct` at temperature 0, `nomic-embed-text` for similarity.

Four measurements, not one:

- **claims** — raw count. Rises with chunk count by construction; meaningless alone.
- **unique** — after collapsing near-duplicates at cosine ≥ 0.93.
- **coverage** — of the union of everything *any* setting found, how much did this one
  recover? This is the measurement that matters.
- **seconds** — what it cost.

**Compromises, recorded before results were read:** one extraction model; three documents
plus one transcript, enough to avoid a single-source artifact but not to generalise across
all writing; "sameness" inherited from the embedding model with the threshold fixed at 0.93
in advance; and **claim correctness is not measured at all** — this asks how much is found,
not whether it is true.

**Prediction, registered before running:** more claims at smaller chunks, but with rising
duplication, and a coverage gain that flattens around 8–12k characters.

---

## Part A — written documentation

Three real documents from different projects and of different character: a tutorial-style
explainer (47 KB), a backend build guide (45 KB), a troubleshooting reference (60 KB).

Union of all findings across all six settings: **635 distinct claims.**

| chunk chars | claims | unique | duplicate rate | coverage | seconds |
|---:|---:|---:|---:|---:|---:|
| 1,000 | 347 | 337 | 3% | **53%** | 1030 |
| 2,000 | 280 | 275 | 2% | 44% | 853 |
| 4,000 | 193 | 192 | 1% | 31% | 609 |
| 12,000 | 69 | 67 | 3% | 11% | 249 |
| 30,000 | 49 | 49 | 0% | 8% | 206 |
| 120,000 *(original default)* | 24 | 24 | 0% | **4%** | 135 |

**The prediction was wrong on two of three counts.** Duplication does not rise — 0–3%
everywhere, so the extra claims at small sizes are genuinely distinct. And coverage does not
flatten anywhere: it is still climbing at 1,000, the smallest size measured.

> ### Correction to the first published table
>
> The first study measured only 4,000 and above, and reported 4,000 at **70% coverage**.
> That number was computed against a union of 274 claims — everything the four settings then
> tested had found between them. Adding 1,000 and 2,000 revealed **361 further claims that
> no earlier setting had found at all**, growing the union to 635 and putting 4,000 at 31%.
>
> Nothing was miscalculated. But coverage is only ever relative to what has been looked for,
> so the earlier figure overstated how complete 4,000 was, and the same caveat applies to
> every number in this document: **53% at 1,000 chars is 53% of what these six settings
> found, not of what exists.**

## Part B — a spoken transcript

A 25-minute talk on running large models locally (21.3 KB after flattening captions from
202 KB of WebVTT). Its own separate union of **76 claims**, deliberately not merged with
Part A — merging would have changed Part A's union and invalidated its figures.

| chunk chars | claims | unique | coverage | seconds |
|---:|---:|---:|---:|---:|
| 1,000 | 28 | 28 | 37% | 94 |
| 2,000 | 30 | 29 | **39%** | 106 |
| 4,000 | 19 | 19 | 25% | 68 |
| 40,000 *(whole transcript)* | 7 | 7 | **9%** | 30 |

**Speech has a turning point that documentation does not.** The collapse at whole-document
size is the same as Part A — 9% against 4% — but below 2,000 the gain stops, and 1,000 is
marginally *worse* than 2,000 rather than better.

A plausible mechanism, untested: written prose packs a claim into a sentence, while in
speech a claim's subject and its qualifier can sit a paragraph apart, so too small a window
cuts claims in half. **This rests on one transcript, and the 37%-versus-39% gap is small
enough to be noise.** The safe reading is "no evidence that going below 2,000 helps for
speech", not "1,000 is worse for speech".

## Why this matters more than the counts suggest

Inspecting *which* claims each setting finds is the real result. In the first study, **185 of
the 192 claims found at 4,000 characters were missed entirely at 120,000.**

What the largest setting found — the document's topic sentences:

> Flash Attention reduces the memory requirements for self-attention layers from quadratic
> to linear with respect to the number of input tokens.

What it missed — the operational specifics:

> Setting `BYPASS_PYDUB_PREPROCESSING=true` skips Open WebUI's pydub-based MP3 conversion,
> compression, and chunk splitting, reducing CPU usage and latency on large files.
>
> Redis is required when running multiple workers or replicas to handle WebSocket
> connections and session syncing.

The same pattern holds for speech. At 2,000 characters the transcript yielded figures a
viewer could act on — 16.5 tokens/second on a stock RTX 3060, 24.4 after dropping from 12
threads to 6 (one per real core), a RAM cliff where 32 GB sustains 22 tokens/second and
20 GB collapses to 9. At whole-transcript size, seven general observations.

Given everything at once, the model returns the abstract and drops the detail. **For a tool
whose purpose is finding what is new to a reader, that is the worst possible bias**, and not
merely a quantitative loss: headline claims are exactly the ones already sitting in any
established corpus.

## The design error behind it

Chunk size was derived from the context window. That conflates two unrelated questions: the
context window governs **what fits**; these measurements are about **what the model will
actually enumerate**. A larger context window is not a reason to send a larger chunk.

`chunk_size_for()` now takes a preferred size capped by capacity — and with a 2,000-character
preference the cap can no longer bind, since any window small enough to afford less than that
raises instead. The cap remains for configured overrides.

## Why 2,000 and not 1,000

The two source types disagree, and 2,000 is the honest compromise:

- **Speech**: 2,000 was the best measured value.
- **Documentation**: 1,000 is better (53% against 44%), at ~20% more time.

Choosing 1,000 would optimise for documentation and over-fit the speech result to a single
transcript. Choosing 4,000 was measurably poor for both. `chunk_chars` in `winnow.json`
overrides it: for a corpus that is entirely dense written reference material, **1,000
measurably finds more.**

## Open, deliberately not closed

- **Documentation had not plateaued at 1,000.** Smaller may still be better; 500 is untested.
- **Part B is one transcript.** The turning point at 2,000 needs more spoken material before
  it is worth designing around.
- **Complementarity is unexploited.** In Part A the large settings still found claims the
  small ones missed — likely document-level synthesis that only exists when the model sees
  the whole text. A two-pass strategy (small chunks for detail, one whole-document pass for
  synthesis) may beat either alone. Untested.
- **Correctness is unmeasured *in this file*.** Every table here counts what was found.
  Measured separately in `CORRECTNESS.md`: 88% faithful when graded claim-by-claim (by a
  frontier model, not a human), no fabrication,
  errors all of one kind (a qualifier dropped). Faithfulness *by chunk size* remains
  unmeasured, so nothing here is validated against accuracy.

## A note on the cost projections

The first study projected 1.4 minutes and took 20; the second projected 27 and took ~40. Both
probed a single small chunk and multiplied by the number of calls, but per-call time rises
with chunk size, so a grid spanning several sizes is not made of homogeneous units.

This is the same class of error the production cost gate was already fixed for once —
projecting by file count over unevenly sized files — reappearing in a new guise. **A single
measured unit only projects a run whose units are alike.** The gate in `winnow/cost.py` is
sound for indexing, where chunk size is constant across the run; these ad-hoc study
projections were not, and are not used by the tool.
