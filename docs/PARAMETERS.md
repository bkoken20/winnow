# Parameters

Every setting Winnow has, its default, and what changing it does. Settings live in
`winnow.json` (write a starter one with `winnow init`); pack settings live in the domain
pack's `pack.json`.

Defaults are **best effort, measured on one machine against a handful of sources**. They are
a reasonable starting point, not an optimum — see [Tuning](#tuning-for-your-own-corpus) at
the end.

---

## Corpus and pack

| setting | default | what it does |
|---|---|---|
| `pack` | `ai_tooling` | Which domain pack to use. Lists with `winnow packs`. |
| `packs_root` | *(repo's `packs/`)* | Where to look for packs. Point it outside the repo to keep private packs unpublished. |
| `corpus_path` | `winnow.db` | The SQLite corpus file. One file; back it up by copying it. |
| `notes_path` | *(unset)* | Default folder for `winnow index`. Also settable via the `WINNOW_NOTES` environment variable. |
| `cache_path` | `winnow-cache` | Where material fetched from a URL is kept, one folder per URL. Re-running the same link uses the cache instead of downloading again. |
| `caption_languages` | `en-orig` | Caption track requested from yt-dlp when fetching a URL. `--sub-langs` is a regex, and `en-orig` is the ORIGINAL English track. If a video has none — because it is in another language — Winnow falls back once to `en`, which is YouTube's machine translation, and says so. The old default `en.*` matched both and fetched the same captions twice, through the translation endpoint that rate-limits. |

## Models

| setting | default | what it does |
|---|---|---|
| `ollama_host` | `http://localhost:11434` | Where Ollama is. |
| `text_model` | `qwen2.5:14b-instruct` | Extracts claims. Any capable instruct model works. |
| `text_num_ctx` | `32768` | **Set this to your model's real context length.** Ollama silently truncates to a small default if the value is wrong or unset, and extraction then reports finding nothing at all — no error, no warning. The single most costly setting to get wrong. |
| `vision_model` | `qwen2.5vl:7b` | Describes sampled frames. Only used when the pack sets `use_frames`. |
| `vision_num_ctx` | `8192` | Same rule as `text_num_ctx`, for the vision model. |
| `frame_every_seconds` | `60` | Sample one frame per this many seconds of video. |
| `max_frames` | `20` | Hard cap on frames per item. One vision call each, several seconds apiece, on the one path with **no cost gate** — so the default is deliberately modest. **Not measured:** no experiment here establishes how many frames are worth describing, unlike the chunking defaults. Treat both as conservative guesses. |
| `embed_model` | `nomic-embed-text` | Embeds claims for similarity. **Changing it under an existing corpus is refused**, not warned: vectors from two models cannot be compared, so the old corpus would be invisible and every claim would look new. Either change it back, or point `corpus_path` at a fresh file and re-index. `winnow status` flags an unusable corpus. |
| `embed_backend` | `ollama` | `ollama` for real embeddings. `hashing` is a deterministic offline stand-in **for tests only** — it produces meaningless similarity, and any verdict computed with it is stamped so it can be identified and discarded. These two are the whole list: any other value is refused when the configuration is read (exit 2), rather than accepted and discovered later. Every command that could act on hashed vectors — `status`, `index`, `rejudge`, `ingest` — says so before it does. |

## Extraction

| setting | default | what it does |
|---|---|---|
| `chunk_chars` | `2000` | How much text goes into one extraction call. **Not** derived from the context window: the window governs what *fits*, this governs what the model actually enumerates. Larger values make the model summarise instead of listing — at 120,000 it recovered 4% of findable claims against 44% at 2,000. |
| `ingest_extra_passes` | `[1000, 4000]` | Extra passes over the same text at other chunk sizes, used when judging new material. Different boundaries put different sentences beside each other, so each pass finds claims the others miss. Three passes took a 25-minute talk from 39% coverage to 92%, costing about three extra minutes. `[]` disables. |
| `index_extra_passes` | `[]` | The same, for corpus indexing — **off by default**, because the cost asymmetry is severe: on a 7.5 MB corpus one pass is projected at 11.6 hours and three at 34.8 — projected from measured throughput, not a timed run. Turn it on if corpus quality matters more than a day of compute. |
| `duplicate_threshold` | `0.93` | Claims closer than this (cosine) to one already in the corpus are not stored. **This is the tool's scaling limit:** each new claim is compared against every stored claim, so indexing cost grows quadratically — measured at ~0.039 ms per stored claim per comparison, i.e. ~390 ms per insert at 10,000 claims. The projection accounts for it; `0` disables suppression and removes the cost. Necessary once more than one pass runs, since passes produce genuine rewordings of the same assertion (~19% of a merged set). **Measured on one real ingest at the shipped default: 38 claims reported, of which 5 pairs scored 0.90 or above — the closest at 0.925, the same sentence reworded.** Lower it toward 0.90 if repeated points bother you more than losing a genuinely distinct claim; that trade has not been measured here. `0` disables suppression entirely. |

## Judging

| setting | default | what it does |
|---|---|---|
| `judge_model` | *(empty)* | Empty means **tier 0**: novelty by embedding similarity alone, no language model, no API key. Set a model name to enable **tier 1**, which adds specificity, evidence and red-flag assessment. |
| `judge_num_ctx` | `8192` | Context window for the tier-1 judge. Same rule as every other `num_ctx`: set it to the judge model's real capacity. |
| `judge_location` | `local` | `local` or `cloud`. Purely declarative — it does not route anything, it determines what `winnow status` tells you about data leaving your machine. Set it honestly. |

## Reading the score

Every verdict prints a number:

```
[NEW    ] 0.70  A 177 billion parameter model can run effectively on a 5-year-old GPU...
[known  ] 0.94  Quantising below Q4 costs noticeable accuracy on small models.
```

That number is the **cosine similarity between this claim and the nearest OTHER claim in
your corpus** — the claim's own stored copy, if it has one, is excluded, because a claim is
not evidence about itself. It runs 0 to 1.

**Higher means you have seen it before.** It is a similarity score, not a confidence score
and not a novelty score, so a *low* number beside `NEW` is the consistent reading: nothing in
your corpus came close. `0.00` means the corpus is empty, or holds nothing comparable.

Three cutoffs sit on that one axis, and their order is the thing to understand:

| score | verdict | stored? |
|---|---|---|
| below `0.75` | `new` | yes |
| `0.75` – `0.90` | `variant` — a recognisable variation of something you have | yes |
| `0.90` – `0.93` | `known` | **yes** — reported as known, but still added to the corpus |
| `0.93` and above | `known` | no — suppressed as a near-duplicate (`duplicate_threshold`) |

The two upper numbers were chosen for different jobs and are not interchangeable. `0.90`
answers *"should I tell the reader they already know this?"*; `0.93` answers *"is this so
close to something stored that keeping it would just echo the corpus back at itself?"*. The
gap between them is a real state: a claim can be reported `known` and still be kept.

Below the pack's `min_corpus`, no cutoff is applied at all — the verdict is `unknown` and
the score is still shown, so you can see how close the nearest match was even when Winnow
declines to rule on it.

**One other verdict skips the cutoffs.** A claim that is *already stored* — you are ingesting
something for the second time — is `known` whatever it scores, because the corpus
demonstrably contains it. Its score is still the real distance to the nearest *other* claim,
so it can read low beside `known`; the rationale on that verdict says which case it is.

**The thresholds are calibrated for `nomic-embed-text`.** Similarity scales differ between
embedding models, so these numbers mean something different under another one — which is
part of why changing `embed_model` under an existing corpus is refused rather than warned
about.

The novelty cutoffs are constants in `winnow/judge.py` (`SIMILARITY_KNOWN`,
`SIMILARITY_VARIANT`), not config; `duplicate_threshold` is config. If you are tuning, tune
`duplicate_threshold` first — it is the one with a measured figure attached above, and the
one that changes what you actually read.

## Pack settings (`packs/<name>/pack.json`)

| setting | default | what it does |
|---|---|---|
| `name`, `version` | — | `version` is recorded in every verdict, so you can tell later which pack produced what. Bump it when you change prompts or schema. |
| `description` | — | One line, shown by `winnow packs`. |
| `schema` | — | The fields a claim has in this domain. Documentation for you and for the prompt; Winnow stores whatever the model returns. |
| `extract_prompt` | — | File containing the extraction prompt. **Must contain the literal token `__TEXT__`**, enforced when the pack loads — without it the model gets no source text and answers by inventing claims or returning nothing, with no error anywhere. |
| `frame_prompt` | — | File containing the frame-description prompt. Ask for prose, never JSON. |
| `starter_sources` | — | File listing public sources for seeding a corpus. |
| `use_frames` | `false` | Whether to sample and describe frames. Leave off unless meaning genuinely lives on screen in your domain. Setting it true with no `frame_prompt` is refused at load. |
| `min_corpus` | `25` | Claims required before any novelty verdict is issued — counting *other* claims, never the one being judged. Below it, everything comes back `unknown` rather than `new`. So a corpus of exactly 25 still reports `unknown` when re-judged, because each claim then rests on 24 peers. Raise for broad domains, lower for narrow ones. |

**Every setting is checked when the file is read.** A value of the wrong type, a size of
zero or less (`text_num_ctx`, `vision_num_ctx`, `judge_num_ctx`, `chunk_chars`,
`frame_every_seconds`, `max_frames`), or a `duplicate_threshold` outside 0–1 is refused by
name with exit 2, before anything runs. `true` is not a number here even though Python
counts it as one, and `duplicate_threshold: 5.0` used to be accepted in silence — no
similarity reaches 5, so de-duplication was off and nothing said so.

## Command-line flags

| flag | applies to | what it does |
|---|---|---|
| `--config PATH` | all | Use a different `winnow.json`. Accepted on either side of the command: `winnow --config x.json ingest URL` and `winnow ingest URL --config x.json` are the same thing. |
| `--accept-minutes N` | `index`, `rejudge` | Accept a projected run of N minutes. Winnow times one real file, projects the whole run by text volume **plus de-duplication scanning**, shows you the number, and refuses runs over ~2 minutes until you accept a budget that covers it. There is no flag that skips the measurement, and acceptance does not silence the number. `rejudge` is gated the same way, but only at tier 1: with a `judge_model` set it is one model call per claim, while at tier 0 it is embeddings only and runs without ceremony. |
| `--new-only` | `ingest` | Print only claims judged `new`. |
| `--with-video` | `ingest` | Also download the video so frames can be described. Much larger; captions alone are enough unless the pack uses frames. |
| `--refetch` | `ingest` | Ignore cached material for this URL and fetch it again. |
| `--force` | `init` | Replace an existing config with defaults. Without it, `init` refuses rather than overwriting a file you already own. |

## Environment

| variable | what it does |
|---|---|
| `WINNOW_NOTES` | Fallback for `notes_path`. |

---

## Tuning for your own corpus

The defaults were measured on one machine, one extraction model, three documentation files
and one spoken transcript. They are a starting point. Three that are genuinely worth
revisiting for your own material:

**`chunk_chars`** — the highest-leverage setting by a wide margin. Dense written reference
material did measurably better at `1000` than at `2000` (53% vs 44% coverage, ~20% more
time). Speech peaked at `2000` and gained nothing below it. If your corpus is all one type,
tune for that type.

**`index_extra_passes`** — off by default purely on cost. If your corpus is small, or you
can leave a machine running, turning it on materially improves what the corpus contains, and
corpus quality is what every later novelty verdict depends on.

**`min_corpus`** — governs how long the tool stays silent before it will commit to a
verdict. The default is deliberately conservative.

The measurements behind these are in `experiments/`, with methods and caveats. The most
important caveat, which applies to every coverage figure quoted anywhere in this repository:
**coverage is measured against the union of what the tested settings found between them, not
against what exists.** Adding a new setting enlarges the union and lowers every existing
figure. Compare within one study; never quote a figure from one study against another.

**What is not measured:** whether claims are *correct* varies with these settings.
Grading 25 claims one by one against their source found 88% faithful with no fabrication
(`experiments/CORRECTNESS.md` — done by a frontier model, not a human, and the file says so).
Faithfulness *by chunk size* could not be measured at all, because no local judge tested
could detect the error class. If you tune aggressively for volume, you are trading against
an accuracy figure nobody has measured.
