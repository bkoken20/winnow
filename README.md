# Winnow

**Tell me what's actually new.**

Most of any talk or article restates things you have already met. Winnow pulls the claims
out of new material, compares them against a corpus of what is already known, and tells you
which few are genuinely new — instead of handing you another summary of things you knew last
year.

**What it takes:** a video URL, or a transcript, or a folder holding one.

```bash
winnow ingest https://youtu.be/SOME_VIDEO --new-only
```

Captions are fetched with yt-dlp — which you install, and which Winnow never installs for
you — and the exact command is printed before it runs. Nothing is downloaded silently, and
video itself is only fetched with `--with-video`, for packs that describe frames.

It does not transcribe: a video with no captions is a stop, not a silent empty result. It
does not read PDFs. [docs/ACQUISITION.md](docs/ACQUISITION.md) covers both, including
producing a transcript yourself with faster-whisper.

It runs locally. With no configuration at all, nothing leaves your machine.

```
$ winnow ingest ./talk/

7 claims extracted

[known  ] 0.94  Quantising below Q4 costs noticeable accuracy on small models
[known  ] 0.91  Retrieval quality matters more than model size for document QA
[VARIANT] 0.81  Speculative decoding helps most at batch size 1
[NEW    ] 0.32  Prefix caching cuts time-to-first-token by ~60% on repeated system prompts
[known  ] 0.96  You should set the context window explicitly rather than trusting defaults
[known  ] 0.89  GGUF quantisation formats trade size against perplexity
[NEW    ] 0.28  Draft models below 1B params stop paying for themselves above 4-way batching
```

Five of those you already had. Two are worth your time.

## Why this rather than a summarizer

A summarizer tells you what a video said. It cannot tell you whether you needed to watch it.
That question requires knowing what you already know, which means keeping a corpus — and
that corpus is the whole point. Winnow is a **corpus-level** tool: the verdict is always
relative to your accumulated knowledge, never to the material in isolation.

## How it works

```
   you acquire material            (Winnow never downloads — see docs/ACQUISITION.md)
              ↓
   transcript, and optionally sampled frames
              ↓
   claim extraction                (local model, guided by a domain pack)
              ↓
   ┌────────────────────────────────────────────┐
   │  novelty · specificity · evidence · flags  │
   └────────────────────────────────────────────┘
              ↓
   verdicts, stamped with what judged them
```

**Two tiers of judgement:**

- **Tier 0 (default, no configuration).** Novelty by embedding similarity against your
  corpus. No API key, no large model, works on any machine — "have I seen this before" is a
  similarity question, and embeddings answer it better and far more cheaply than a language
  model would.
- **Tier 1 (optional).** Add a language model for specificity, evidence quality, red flags
  and nuanced novelty — the same mechanism dressed in new vocabulary. The judge is pluggable:
  a 7B model locally, a 70B on serious hardware, or a cloud API. Your hardware, your call.

## How this is meant to be run

**Local models do the volume. An expensive model does the final call.**

That division is the whole economic argument, and it is measured rather than assumed:

| stage | who does it | why |
|---|---|---|
| transcription, frame description | local | bulk work, no judgement required |
| claim extraction | local | thousands of calls; this is where the tokens would go |
| novelty by similarity | local embeddings | "have I seen this?" is a distance question, not a reasoning one |
| **the final read** | **you, or a frontier model you direct** | the part local models measurably cannot do |

**What it actually costs, measured.** A 25-minute talk (21 KB of transcript) takes **4.9
minutes** of local compute on a 12 GB consumer GPU and yields **72 claims**. Not a handful
— but 72 short statements is a few minutes of reading against 25 minutes of watching, and
you can read them at your own pace, search them, and keep them.

**On a fresh corpus every one of those 72 comes back `?`** — Winnow refuses to call anything
novel until the corpus passes the pack's minimum, because a blind spot is not a discovery.
The sorting into *known* and *new* is what you get once a corpus exists; the first few
things you feed it are just building one. `--new-only` is what makes the output short, and
it only starts being useful after that point.

**Why the last row is not local.** An independent local judge (27B, a different family from
the extractor) was asked to check extracted claims against their source. It reported
96–100% faithful and **zero** distortions across 85 claims. Hand-checking found three real
distortions in a 25-claim sample — the judge had marked **all three** as supported. A
stricter prompt, demanding a verbatim supporting quote, did no better: still 0 of 3, plus
four false alarms. Two opposite prompt designs, same blindness. See
[experiments/CORRECTNESS.md](experiments/CORRECTNESS.md).

So Winnow deliberately stops where local models stop being trustworthy. It hands you a
short, structured, deduplicated list with its reasoning attached — and the judgement that
actually matters stays with something capable of making it.

**The tool never calls a cloud API itself.** `judge_location` is a declaration used by
`winnow status` to tell you what leaves your machine; it does not route anything. Tier-1
judging runs against whatever model server you point `ollama_host` at. The "expensive model"
in the table above is you, or an assistant you are working with, reading Winnow's output —
which is exactly the arrangement this tool was built under.

## Two rules it will not bend

**A thin corpus produces no verdict.** Below the pack's minimum, novelty comes back as
`unknown`, never `new`. A blind spot is not a discovery, and a tool that confidently calls
everything novel on day one is worse than no tool.

**Every verdict records what judged it** — embedding model, backend, judge model, prompt
version, pack version. Verdicts from different judges are not comparable, and a corpus that
silently mixes them is worthless six months later.

## Install

Winnow is distributed by clone, not as a package — it needs a model server, models and
(optionally) ffmpeg, so a package install could never produce a working tool on its own.

```bash
git clone https://github.com/<you>/winnow.git
cd Winnow
pip install -e .                         # installs the `winnow` command
pip install -r requirements.txt          # pytest, only needed to run the tests
```

You also need [Ollama](https://ollama.com) running, with:

```bash
ollama pull qwen2.5:14b-instruct         # extraction (any capable instruct model works)
ollama pull nomic-embed-text             # embeddings
ollama pull qwen2.5vl:7b                 # optional, only for frame description
```

Model names are not sacred. Substitute whatever you have — but **check the real context
length of your extraction model and set `text_num_ctx` to match**, because an over-long
prompt is silently truncated and extraction then reports finding nothing at all.

## Start

```bash
winnow init                              # writes winnow.json (refuses to overwrite one)
winnow status                            # configuration, corpus size, and what leaves the box
winnow packs                             # domain packs available
```

**Seed the corpus.** It does not have to be your own writing — it is simply what is already
known in your field:

```bash
python scripts/fetch_starter_corpus.py --pack ai_tooling --dest ~/notes
winnow index ~/notes
```

Long indexing runs are measured before they start: Winnow processes one file, times it,
projects the whole run, shows you the number, and waits for you to accept it.

**Then judge new material:**

```bash
winnow ingest ./talk/ --new-only
```

Judging reads the material three times, at three different chunk sizes, by default. That sounds
wasteful and is not: different chunk boundaries put different sentences beside each other, so
later passes find claims the first missed — measured at 39% coverage for one pass against
92% for three, on a 20-minute talk, for about three extra minutes. Corpus indexing leaves it off, because
there the same choice is the difference between twelve hours and thirty-five
([experiments/TWO_PASS.md](experiments/TWO_PASS.md)).

**As the corpus grows**, claims judged "new" when it was thin may turn out to be
restatements. Re-judging is cheap:

```bash
winnow rejudge
```

## Parameters

Every setting, its default and what changing it does:
**[docs/PARAMETERS.md](docs/PARAMETERS.md)**.

Defaults are best effort — measured on one machine against a handful of sources, and
documented so you can see the reasoning rather than trust it. The highest-leverage one is
`chunk_chars`; the one most likely to silently ruin your results is `text_num_ctx`.

## Domain packs

The only part of Winnow that knows what a subject is about. A pack carries the claim schema,
the extraction and frame prompts, the corpus threshold and a starter-source list. Everything
else in the codebase is domain-blind.

`ai_tooling` ships as the worked example. Writing your own is a folder and a JSON file — see
[docs/DOMAIN_PACKS.md](docs/DOMAIN_PACKS.md). Packs are configuration, not code, so a private
pack can live outside the repository and never be published.

## Privacy

`winnow status` states exactly what leaves your machine under your current settings.

By default: nothing. Embeddings and extraction run against local Ollama. Enable a cloud judge
and Winnow says plainly, before you use it, that claim text and the most similar claims from
your corpus will be transmitted — because attaching a personal knowledge base to a remote
model is precisely the thing you deserve to be warned about beforehand.

## Tests

```bash
python -m pytest tests/ -q
```

The suite runs offline: no model server, no network. Twenty-two behaviours the tool guarantees have been
verified to actually fail when the behaviour backing them is removed — see
[tests/PERTURBATION.md](tests/PERTURBATION.md). A green test that could not have failed is
not evidence.

## Licence

MIT. See [LICENSE](LICENSE).
