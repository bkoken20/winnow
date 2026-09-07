# Are the extracted claims faithful to the source?

**88% clean on a sample of 25 graded claim-by-claim against the source, with 12% distorted — and the distortions share a
single shape.** An automated judge put it at 96–100%, and that figure is **withdrawn**: the
judge missed every distortion a human found.

## What is being measured

**Faithfulness to the source, not truth about the world.** If the speaker is wrong and the
claim repeats him accurately, the extraction is correct. Four verdicts: SUPPORTED,
DISTORTED (the source says something close, but a number, condition or subject has changed),
UNSUPPORTED, UNCLEAR.

This matters because every other measurement in these experiments counts what was *found*.
A pass that doubled the claim count while halving accuracy would look identical in those
tables, so the whole multi-pass result rested on an untested assumption.

## Method

85 claims from a 25-minute spoken transcript, across four chunk sizes. For each claim, the
three transcript windows nearest it by embedding similarity are retrieved and the claim is
judged against them.

- **Automated judge:** `gemma3:27b` — deliberately a different family and size from the
  extractor (`qwen2.5:14b-instruct`). A model grading its own output shares its blind spots.
- **Independent calibration:** a random 25-claim sample graded claim-by-claim against the
  source by a frontier model (Claude Opus 5) — NOT a human, and not independent of all
  model error, though it is a different family, scale and vendor from both the extractor
  and the judge. Recorded before the
  judge's verdicts were opened. Without this step the automated number is worthless, because
  nothing establishes that the judge can detect the errors being counted.

## Result 1: the automated judge cannot be trusted here

| chunk | n | judge: supported | distorted | unsupported |
|---:|---:|---:|---:|---:|
| 1,000 | 30 | 100% | 0% | 0% |
| 2,000 | 29 | 100% | 0% | 0% |
| 4,000 | 19 | 95% | 0% | 5% |
| 40,000 | 7 | 86% | 0% | 14% |

**Zero DISTORTED across all 85 claims.** A judge that never once uses one of its four
categories is a warning, not a clean result — and the hand-graded sample confirms it: of the
three distortions found by the frontier grader, `gemma3:27b` marked **all three SUPPORTED**.

Agreement with hand grading: **21/25 (84%)**, but the disagreements are not random. The judge
is reliable on straightforward restatements and blind to exactly the error class that
matters. It is usable as a fabrication detector, not as a faithfulness detector.

**So the by-chunk-size table above says nothing** about whether smaller chunks distort more.
An instrument that cannot detect the error cannot compare its rate across conditions. That
question remains genuinely unmeasured.

## Result 2: independently graded faithfulness is 88%

22 SUPPORTED, 3 DISTORTED, 0 unsupported, 0 unclear.

**All three distortions have the same shape: the claim is stronger or simpler than the
source.**

| source says | claim says |
|---|---|
| runs on a 12 GB GPU "and not crawling" | runs "without performance degradation" |
| the author's machine *has* 61 GB of RAM | the model *requires* 61 GB of RAM |
| the phrase book **adds** 51B parameters and cuts **computation** | the phrase book "reduces the number of **parameters** needed" |

The third inverts the source outright. The second turns a machine specification into a
requirement — and the same video demonstrates the model running in 12 GB. Neither is a
hallucination; both are a qualifier being dropped in the course of making a standalone
sentence out of conversational speech.

## Result 3: source transcription errors propagate silently

One claim read "2526 tokens per second on a 3060" — an absurd figure. It is **faithfully
extracted**: YouTube's auto-captions transcribe "25–26 tokens a second" as "2526 tokens a
second", and the extractor reproduced what it was given.

Winnow cannot detect this, and nothing downstream will either — the figure is wrong but the
extraction is correct, so no faithfulness check can catch it. **Claims drawn from
machine-generated captions carry a transcription risk that claims from written sources do
not.** Human-authored subtitles, where available, avoid it.

## A grading error by the frontier grader, recorded rather than quietly fixed

My first hand pass produced 5 UNCLEAR and 4 DISTORTED verdicts. Six of those were wrong: I
graded from excerpts that my own print statement had truncated to ~900 characters, so I was
calling text absent that was simply off-screen. Re-graded against the full excerpts, five
UNCLEARs became SUPPORTED and one DISTORTED became SUPPORTED.

An underpowered instrument produced false negatives that read as findings — the identical
failure this study exists to detect in the model. Recorded in
`correctness_human_grades.json` alongside the corrected verdicts.

## What this does and does not license

**Supports:** extraction is substantially faithful. 88% clean, with no fabrication observed
in 25 independently checked claims — the errors were all degradations of real statements, never
invention.

**Does not support:** any claim that faithfulness is equal across chunk sizes. That
comparison needs an instrument that can see distortions, and the automated judge cannot.
The multi-pass defaults therefore still rest on volume evidence alone.

**Does not support:** a 99% figure, or any automated faithfulness number produced by a local
judge of this class without human calibration.

## Open

- **Faithfulness by chunk size** — the question that would validate or undermine the
  multi-pass defaults. Needs either a much better judge or a larger hand-graded sample
  stratified by size.
- **Written sources are untested.** All 25 hand-graded claims came from speech. Written
  documentation has cleaner sentence boundaries and no ASR risk, so its error profile is
  probably different and possibly better.
- **n = 25, one source, one extraction model.** The 88% figure carries a wide interval and
  should be treated as an order of magnitude, not a measurement to quote.
- ~~A stricter judge prompt is untried.~~ **Tested and refuted — see below.**

---

# Addendum: the strict judge fails too

The leniency hypothesis was that the judge agreed too easily because it was asked to assess
rather than to prove. Tested with a prompt that (a) frames the task adversarially, (b)
requires a **verbatim quotation** of the supporting span, and (c) describes *strengthening*
as a failure mode in general terms — deliberately not naming the three specific errors found
by hand, which would be fitting the prompt to the test set.

The quoted spans are then **verified programmatically** against the source: a normalised
substring check, not another model's opinion.

## Result: strictly worse

| | lenient prompt | strict prompt |
|---|---:|---:|
| agreement with hand grades (n=25) | 84% | **72%** |
| the three known distortions caught | 0/3 | **0/3** |
| false alarms on faithful claims | 1 | **4** |

No improvement whatsoever on the measurement that mattered, and four faithful claims newly
flagged. The prompt made the judge suspicious, not discerning — which is not a trade worth
making, since a checker that cries wolf on faithful claims is as unusable as one that waves
distortions through.

## Why it failed, in its own words

The prompt explicitly warned that *"a source describing what one machine HAS does not support
a claim about what is REQUIRED"*. Presented with precisely that error, the strict judge
answered:

> The quote directly states the RAM amount (61 gigs) and the prompt processing requirement.

And on the claim that inverts the phrase book — the source says it **adds** 51B parameters
and reduces **computation**:

> The claim and quote both discuss reducing parameter needs.

It is matching on topic, not checking direction or attachment. Naming the failure mode in the
instructions changed nothing, because the model is not performing the comparison the
instructions describe.

## What the mechanical check found

**86% of SUPPORTED verdicts cite a span actually present in the source.** One verdict in
seven quotes something that is not verbatim in the text, despite an explicit instruction to
copy "character for character".

This is the only measurement here not produced by a model judging a model, and it is
independently informative: a judge that cannot reliably quote its own evidence is not going
to reliably compare that evidence against a claim.

## The conclusion this forces

Two prompts of opposite design, same judge, same 0/3. **The limitation is the model, not the
prompt.** Automated faithfulness checking is not available from a local 27B-class model at
the precision these errors require, and no further prompt engineering is warranted without
first establishing that some judge, somewhere, can detect this error class at all.

Consequences:

- The **88% hand-graded figure remains the only trustworthy correctness number** in this
  repository.
- **Faithfulness by chunk size stays unmeasured.** Both judges' by-size tables are noise:
  an instrument scoring 0/3 on known errors cannot compare error rates across conditions.
- Winnow should **not** ship an automated faithfulness check built on a local judge. If
  faithfulness checking is ever wanted, this is the one place in the design where a
  frontier-class cloud judge would add a capability that no local model at this scale
  provides — which is a real argument for the tier-1 path, not a reason to fake it locally.

## Still open

- **Whether any judge can do this.** A frontier model was not tested. The hand grading was
  done by one, informally, and found the errors — but that is not the same as a measured
  head-to-head, and it says nothing about smaller cloud models.
- **A quotation-only pipeline is untried**: force the quote, verify it mechanically, and
  discard the model's verdict entirely, judging support purely by whether a verifiable span
  exists. That uses the model for retrieval rather than for judgement, which is the part it
  demonstrably does better.
