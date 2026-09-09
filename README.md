# Winnow

**Give it a YouTube link. It tells you what's in the video that you don't already know.**

```bash
winnow ingest https://youtu.be/IH8XmxiwliQ --new-only
```

Winnow fetches the captions, pulls out every specific claim the video makes, and checks each
one against a corpus of what you have already watched and read. Then it shows you the few
that are new. Twenty-five minutes of video becomes a list you can read in two, and the parts
you already knew are marked as such instead of wasting your time again.

It is not a summarizer. A summary tells you what a video said; it cannot tell you whether
you needed to watch it. That question needs a memory of what you already know, which is what
the corpus is.

**Any topic.** What counts as a claim, and what "already known" means, live in a *domain
pack* — a folder with a prompt and a schema. One ships, for AI and local-LLM tooling.
Writing another is a JSON file and a prompt, not a fork.

Links are the common case, not the only one: anything you can put in a text file works too —
a transcript you made yourself, documentation, your own notes. Captions come from yt-dlp,
which you install and which Winnow never installs for you, with the exact command printed
before it runs. Winnow does not transcribe, so a video with no captions is a stop rather
than a silent empty result, and it does not read PDFs.
[docs/ACQUISITION.md](docs/ACQUISITION.md) covers both.

**Everything except fetching runs on your machine.** Extraction, embeddings and judging
are local by default and need no API key. The one thing that reaches the network is
yt-dlp getting captions, which only happens when you pass a URL, and which prints its
command first. `winnow status` states exactly what leaves your machine under your
current settings.

```
$ winnow ingest https://youtu.be/IH8XmxiwliQ

running: yt-dlp --skip-download --write-subs --write-auto-subs --sub-format vtt ...
72 claims after de-duplication

[NEW    ] 0.70  A 177 billion parameter model can run effectively on a 5-year-old GPU with 12GB of VRAM.
[NEW    ] 0.59  The Quen 4 exp model includes an additional 51 billion parameters in the form of a lookup table.
[NEW    ] 0.63  The Quen 4 exp model architecture includes a phrase book in addition to the standard dicti...
[NEW    ] 0.68  A 3-bit quantized 177 billion parameter model runs on a server with an RTX 3060 and 61 GB...
[NEW    ] 0.66  The model runs at 16.5 tokens per second on a used gaming card.
```

Real output, copied from a run, not an illustration: a 25-minute talk judged against a
corpus built from llama.cpp, Ollama and vLLM documentation. Everything came back `NEW`,
which is the right answer — that corpus knows about quantisation and inference backends,
and nothing at all about this architecture. Feed it a video on a subject your corpus does
cover and most lines read `known`.

The number is the similarity between that claim and the closest thing already in your
corpus, so **higher means you have seen it before** — which is why the new ones score low.
The cutoffs, and what happens in each band, are in
[docs/PARAMETERS.md](docs/PARAMETERS.md#reading-the-score).

## Quickstart

Fourteen minutes from clone to a real verdict, measured on a 12 GB consumer GPU:

```bash
git clone https://github.com/bkoken20/winnow.git && cd winnow
pip install -e .                    # the `winnow` command
pip install -U yt-dlp               # only if you want to pass URLs

# 1. build a small corpus of what is already known in the field   (23s + 8 min)
python scripts/fetch_starter_corpus.py --pack ai_tooling --dest ./notes --limit 80
winnow index ./notes --accept-minutes 15

# 2. judge something against it                                    (5 min)
winnow ingest https://youtu.be/SOME_TALK --new-only
```

You also need [Ollama](https://ollama.com) running with three models pulled — see
[Install](#install).

`--limit 80` keeps step 1 to eight minutes and yields ~110 claims, past the 25 needed before
Winnow will call anything novel — that part is measured. Drop the limit and the run is much
longer, on material whose size this project has not measured end to end; Winnow indexes one
file, projects the whole run from it, and shows you the number before it starts, so you find
out in seconds rather than from a figure quoted here.

## Why this rather than a summarizer

A summarizer tells you what a video said. It cannot tell you whether you needed to watch it.
That question requires knowing what you already know, which means keeping a corpus — and
that corpus is the whole point. Winnow is a **corpus-level** tool: the verdict is always
relative to your accumulated knowledge, never to the material in isolation.

## How it works

```
   a YouTube link                  (or a transcript, or a folder you already have)
              ↓
   captions via yt-dlp             (you install it; the command is printed before it runs)
              ↓
   transcript, and optionally sampled frames   (frames only with --with-video)
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
| fetching captions | yt-dlp, on your machine | no judgement required; Winnow never transcribes |
| frame description | local vision model | only with `--with-video`, for packs that use it |
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
98% faithful and **zero** distortions across 85 claims. Grading those claims one by one
against the source found three real distortions in a 25-claim sample — the judge had marked
**all three** as supported. (That grading was done by a frontier model, not by a human.) A
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

**Every verdict records what judged it** — tier, embedding model, backend, judge model,
judge location, prompt version, pack version, and whether the material stayed on this
machine. Verdicts from
different judges are not comparable, and a corpus that silently mixes them is worthless six
months later.

**Whether the material stayed on this machine** is the one to read later, and it is not the
same as judge location. It combines the address with your own correction to it, and it is
recorded on every verdict at both tiers — embeddings go to the same host as judging.
**Judge location** is what you *declared*; it routes nothing, and it is blank on verdicts
where no judge ran. This paragraph used to say judge location "says whether the claim text
was sent anywhere". It does not: `ollama_host` decides that, and only you know whether a
loopback address forwards somewhere else.

## Install

Winnow is distributed by clone, not as a package — it needs a model server, models and
(optionally) ffmpeg, so a package install could never produce a working tool on its own.

```bash
git clone https://github.com/bkoken20/winnow.git
cd winnow
pip install -e .                         # installs the `winnow` command
pip install -U yt-dlp                    # only to pass URLs; Winnow never installs it for you
pip install -r requirements.txt          # pytest, pyflakes, PyYAML, and tomli below 3.11 -- only to run the tests
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
python scripts/fetch_starter_corpus.py --pack ai_tooling --dest ./notes --limit 80
winnow index ./notes --accept-minutes 15
```

Drop `--limit` for the full starter set, which is considerably longer — the projection
will tell you how much. Long runs are measured before they start: Winnow indexes one file,
times it, projects the whole run including de-duplication, shows you the number, and will
not proceed until you accept a budget that covers it.

The file it times is the median-sized one **that has something in it**. Empty files are
skipped for that purpose: timing one measures nothing, and a folder where more than half the
files are empty used to project a real run at roughly zero.

**Then judge something:**

```bash
winnow ingest https://youtu.be/SOME_VIDEO --new-only   # a link
winnow ingest ./talk/ --new-only                       # or a folder you already have
```

Judging reads the material three times, at three different chunk sizes, by default. That sounds
wasteful and is not: different chunk boundaries put different sentences beside each other, so
later passes find claims the first missed — measured at 39% coverage for one pass against
92% for three, on a 25-minute talk, for about three extra minutes. Corpus indexing leaves it
off, because there the same choice is projected to be the difference between twelve hours
and thirty-five hours — projected from measured throughput, not a run anyone has timed
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
That command is the authority; this section is a summary of it.

**Your material never leaves by default.** Extraction, embeddings and judging all run
against local Ollama, and your notes, transcripts and extracted claims are not transmitted
anywhere.

Five things in this repository can reach the network. All five, in full:

| what | when | what it sends |
|---|---|---|
| **yt-dlp** | `winnow ingest <url>` | contacts the site the link points at. Winnow prints the exact command before running it and sends nothing of yours beyond the link you gave. Pass a file or a folder instead and nothing is fetched at all. |
| **Ollama at `ollama_host`** | every extraction, embedding and judgement | the full text being processed. It defaults to `http://localhost:11434`, so nothing leaves the machine — **`ollama_host` is the single setting that decides this**, and pointing it elsewhere sends everything there. `winnow status` says so plainly when you do. A loopback host is never sent through `http_proxy`, whatever your environment sets; a remote one is, and `status` names the proxy. |
| **`scripts/fetch_starter_corpus.py`** | only when you run it | `git clone --depth 1` against the public repositories listed in the pack's starter-source file. It downloads; it uploads nothing but the clone request. |
| **`pip install -U yt-dlp`** | the documented install | contacts a package index, like any pip install. Winnow never runs it for you. |
| **`pip install -r requirements.txt`** | only to run the tests | the same package index. The runtime itself has no dependencies. |

**`judge_location` routes nothing.** It is a declaration *you* make about where your Ollama
host is, and it does two things: it selects the warning `winnow status` prints, and it is
recorded in every verdict's stamp so you can tell later which verdicts were produced that
way. Setting it to `cloud` does not send anything anywhere — only `ollama_host` does that.
Winnow has no cloud API client of any kind.

**But the warning is worth reading.** If your Ollama host is remote and you enable a judge,
the text of each claim judged plus the most similar claims from your corpus go to that host —
because attaching a personal knowledge base to a remote model is precisely the thing you
deserve to be told about beforehand.

## Tests

```bash
python -m pytest tests/ -q
```

The suite runs offline: no model server, no network. 181 behaviours the tool guarantees have been
verified to actually fail when the behaviour backing them is removed — see
[tests/PERTURBATION.md](tests/PERTURBATION.md). A green test that could not have failed is
not evidence. Three of those were found by mutating the source at random rather than by
choosing what to test, which is the part of that file I would most trust a stranger to
believe.

## Exit codes

`winnow` returns a distinct code per predictable failure, so a script can tell throttling
from a bad path from a model server that is not running. Anything unexpected is deliberately
left to raise with a full traceback rather than being flattened into one of these.

| code | meaning | what to do |
|---|---|---|
| `0` | success — including "found nothing", which is an answer | — |
| `1` | no domain packs found | install with `pip install -e .` from the clone, or set `packs_root` |
| `2` | bad input: missing path, not a folder, a link Winnow cannot use (a missing or mistyped `https://`), malformed JSON, a `winnow.json` that is not a JSON object, a setting whose value cannot be used (an unknown `embed_backend`, a `text_num_ctx` too small to extract from), permission denied, a path that cannot be read or written (a directory where a file belongs, a full disk), a setting of the wrong type or outside its range, or `init` refusing to overwrite | fix the path, link or setting named in the message |
| `3` | run refused — the projection exceeded your accepted budget | re-run with the `--accept-minutes` figure the message gives |
| `4` | Ollama unreachable or erroring | check it is running: `curl -s http://localhost:11434/api/tags` |
| `5` | corpus database error | the message names the corpus path |
| `6` | corpus/model mismatch — it was built with a different embedding model. `winnow status` returns this too, so it is usable as a health check | set `embed_model` back, or start a fresh corpus |
| `7` | invalid pack — it would produce nonsense, so it is refused at load | the message names the file and the problem |
| `8` | yt-dlp not installed | `pip install -U yt-dlp`; Winnow never installs it for you |
| `130` | stopped with Ctrl-C. Anything already stored is kept, and `winnow index` resumes where it stopped | re-run the same command |
| `9` | fetch failed — the video is unavailable/private/region-locked, 403/429 throttling, an out-of-date yt-dlp, or sign-in gating | read yt-dlp's own message in the output; the error lists the causes |

## Releasing

**Publish from a clean checkout, never by copying this folder.** The repository is clean from
Git's point of view, and the working directory is not: it accumulates a corpus database with
your claim text and absolute local paths, a `winnow.json` with more of them, fetched captions
under `winnow-cache/`, and stale `build/` and `*.egg-info` output whose copies of the source
no longer match the tree. All of it is gitignored, so none of it is committed — and all of it
would travel in a copied folder.

```bash
git archive --format=tar.gz -o winnow.tar.gz HEAD   # exactly the tracked files, nothing else
```

or clone into a fresh directory and work from there. `tests/test_what_would_ship.py` checks
the archive both ways: that it carries no local artifact, and that it is still the project.

**PyPI is out of scope.** There is no publish workflow and no credential, and there will not
be one: the wheel excludes `packs/`, so `pip install winnow` produces a tool that exits 1
with `no packs found.` — verified by building the wheel, installing it into a clean virtual
environment and running it. That is deliberate rather than an oversight — Winnow needs a
model server, models and optionally ffmpeg, and a package install cannot deliver any of them,
so it would be an installation that looks successful and does nothing. **The supported
install is `git clone` then `pip install -e .`**, which is what the [Install](#install)
section says and what CI exercises on every push.

The build and `twine check` steps in CI are not left over from a package plan. They read the
same `pyproject.toml` that `pip install -e .` reads, so they catch metadata that would break
the documented install before a user meets it.

## Licence

MIT. See [LICENSE](LICENSE).
