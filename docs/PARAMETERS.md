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
| `caption_languages` | `en.*` | Caption languages requested from yt-dlp when fetching a URL. |

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
| `embed_backend` | `ollama` | `ollama` for real embeddings. `hashing` is a deterministic offline stand-in **for tests only** — it produces meaningless similarity, and any verdict computed with it is stamped so it can be identified and discarded. |

## Extraction

| setting | default | what it does |
|---|---|---|
| `chunk_chars` | `2000` | How much text goes into one extraction call. **Not** derived from the context window: the window governs what *fits*, this governs what the model actually enumerates. Larger values make the model summarise instead of listing — at 120,000 it recovered 4% of findable claims against 44% at 2,000. |
| `ingest_extra_passes` | `[1000, 4000]` | Extra passes over the same text at other chunk sizes, used when judging new material. Different boundaries put different sentences beside each other, so each pass finds claims the others miss. Three passes took a 20-minute talk from 39% coverage to 92%, costing about three extra minutes. `[]` disables. |
| `index_extra_passes` | `[]` | The same, for corpus indexing — **off by default**, because the cost asymmetry is severe: on a 7.5 MB corpus one pass is ~12 hours and three are ~35. Turn it on if corpus quality matters more than a day of compute. |
| `duplicate_threshold` | `0.93` | Claims closer than this (cosine) to one already in the corpus are not stored. **This is the tool's scaling limit:** each new claim is compared against every stored claim, so indexing cost grows quadratically — measured at ~0.039 ms per stored claim per comparison, i.e. ~390 ms per insert at 10,000 claims. The projection accounts for it; `0` disables suppression and removes the cost. Necessary once more than one pass runs, since passes produce genuine rewordings of the same assertion (~19% of a merged set). `0` disables suppression entirely. |

## Judging

| setting | default | what it does |
|---|---|---|
| `judge_model` | *(empty)* | Empty means **tier 0**: novelty by embedding similarity alone, no language model, no API key. Set a model name to enable **tier 1**, which adds specificity, evidence and red-flag assessment. |
| `judge_num_ctx` | `8192` | Context window for the tier-1 judge. Same rule as every other `num_ctx`: set it to the judge model's real capacity. |
| `judge_location` | `local` | `local` or `cloud`. Purely declarative — it does not route anything, it determines what `winnow status` tells you about data leaving your machine. Set it honestly. |

Novelty thresholds are currently constants in `winnow/judge.py`, not config: `0.90` and above
is `known`, `0.75`–`0.90` is `variant`, below is `new`.

## Pack settings (`packs/<name>/pack.json`)

| setting | default | what it does |
|---|---|---|
| `name`, `version` | — | `version` is recorded in every verdict, so you can tell later which pack produced what. Bump it when you change prompts or schema. |
| `description` | — | One line, shown by `winnow packs`. |
| `schema` | — | The fields a claim has in this domain. Documentation for you and for the prompt; Winnow stores whatever the model returns. |
| `extract_prompt` | — | File containing the extraction prompt. Must contain the literal token `__TEXT__`. |
| `frame_prompt` | — | File containing the frame-description prompt. Ask for prose, never JSON. |
| `starter_sources` | — | File listing public sources for seeding a corpus. |
| `use_frames` | `false` | Whether to sample and describe frames. Leave off unless meaning genuinely lives on screen in your domain. |
| `min_corpus` | `25` | Claims required before any novelty verdict is issued — counting *other* claims, never the one being judged. Below it, everything comes back `unknown` rather than `new`. So a corpus of exactly 25 still reports `unknown` when re-judged, because each claim then rests on 24 peers. Raise for broad domains, lower for narrow ones. |

## Command-line flags

| flag | applies to | what it does |
|---|---|---|
| `--config PATH` | all | Use a different `winnow.json`. |
| `--accept-minutes N` | `index` | Accept a projected run of N minutes. Winnow times one real file, projects the whole run by text volume **plus de-duplication scanning**, shows you the number, and refuses runs over ~2 minutes until you accept a budget that covers it. There is no flag that skips the measurement, and acceptance does not silence the number. |
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
Hand-grading found 88% faithful with no fabrication (`experiments/CORRECTNESS.md`), but
faithfulness *by chunk size* could not be measured, because no local judge tested could
detect the error class at all. If you tune aggressively for volume, you are trading against
an accuracy figure nobody has measured.
