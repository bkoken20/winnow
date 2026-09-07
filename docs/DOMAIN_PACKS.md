# Writing a domain pack

A pack is the only part of Winnow that knows what a subject is about. Everything else —
storage, embedding, similarity, verdicts, the CLI — is domain-blind. That is what makes this
one tool rather than one tool per field.

Packs are **configuration, not code**. A pack you keep private simply lives outside the
repository and is never published.

## Layout

```
packs/
  your_domain/
    pack.json              the manifest
    extract_prompt.txt     how to pull claims out of text
    frame_prompt.txt       what matters visually (optional)
    starter_sources.json   public material to seed a corpus (optional)
```

Point Winnow at a packs directory outside the repo with `packs_root` in `winnow.json`.

## pack.json

```json
{
  "name": "your_domain",
  "version": "1",
  "description": "one line, shown by `winnow packs`",
  "schema": {
    "claim": "the assertion itself, stated in one sentence",
    "kind": "the categories that matter in this field",
    "condition": "when it holds",
    "evidence": "what the source offers in support"
  },
  "extract_prompt": "extract_prompt.txt",
  "frame_prompt": "frame_prompt.txt",
  "starter_sources": "starter_sources.json",
  "use_frames": false,
  "min_corpus": 25
}
```

| field | meaning |
|---|---|
| `version` | Bump when you change prompts or schema. It is recorded in every verdict, so you can tell later which pack produced what. |
| `schema` | The fields a claim has in your field. Documentation for you and for the prompt; Winnow stores whatever the model returns. |
| `use_frames` | `false` for most domains. Only true where meaning genuinely lives on screen — and setting it true without a `frame_prompt` is refused at load, since frames would be sampled, described with an empty prompt, and wasted. |
| `min_corpus` | Claims required before novelty verdicts are issued — counting *other* claims, never the one being judged. Below it, everything is `unknown`. A corpus of exactly 25 therefore still reports `unknown` when re-judged. |

## The extraction prompt

`__TEXT__` is replaced with the source text. Use that literal token — **not** `{}` or
`str.format()`, because prompts contain literal JSON braces as output examples and formatting
would raise on the first one.

**A prompt without `__TEXT__` is refused when the pack loads.** Without it the model is asked
to find claims in a prompt containing no source at all, and answers by inventing them or
returning nothing — with no error anywhere. That failure is silent and expensive to trace,
so it is caught at load time instead.

A good extraction prompt does four things:

**1. Defines what counts as a claim in your field, with examples.** This does more work than
anything else in the pack.

**2. Says explicitly what to exclude.** Models are eager. Without a list, you get "this tool
is great" and "remember to subscribe" as claims. Name the junk your domain actually produces.

**3. Fixes the output shape.** Ask for JSON, show the exact structure, and demand nothing
outside it.

**4. Permits an empty result.** State that `{"claims": []}` is a correct answer. Without
this, a model faced with an empty ten minutes will invent something to fill the list — and a
fabricated claim in the corpus poisons every later verdict against it.

```
Return JSON only:

{
  "claims": [
    {"claim": "one self-contained sentence", "kind": "...", "evidence": "..."}
  ]
}

If the material contains no real claims, return {"claims": []}. An empty list is a correct
and useful answer. Do not invent claims to fill it.

SOURCE MATERIAL:
__TEXT__
```

## The frame prompt

Only if `use_frames` is true.

**Ask for prose, never JSON.** Forcing a JSON response on a description prompt makes the
model fight the constraint and emit garbled, hallucinated output — invented numbers, broken
nesting. Winnow's client makes this structurally impossible (`describe_image` has no JSON
option at all), but do not write a prompt that asks for it either.

Give the model an explicit escape for uninteresting frames:

```
If the frame shows none of these — a talking head, a title card, a logo — reply with exactly:

NO_TECHNICAL_CONTENT
```

**Write that token in capitals, and nothing else on the line.** Winnow does not know your
pack's token — you choose it — so it recognises an escape by the only property it can check
without being told: the whole reply is upper case. A sentinel like `nothing here` is not
recognised, and is stored as though it were a real description, then appended to the
transcript under `[ON-SCREEN CONTENT]` where the extractor reads it as something that was
genuinely on screen. Silent, and it degrades the very material frames exist to improve.

Without an escape at all, a model asked to describe a title card will describe it at length,
and that noise ends up in your corpus.

## starter_sources.json

Public, permissively-licensed material a user can fetch to seed a corpus. Winnow ships the
*list*, never the content, so nobody inherits anyone else's licensing.

```json
[
  {
    "name": "project-docs",
    "url": "https://github.com/org/project",
    "paths": ["docs/", "README.md"],
    "license": "Apache-2.0",
    "why": "one line on what claims this contributes"
  }
]
```

Fetched with:

```bash
python scripts/fetch_starter_corpus.py --pack your_domain --dest <folder> --limit 80
```

`--limit` stops after that many files, preferring substantial pages over stubs, so someone
trying your pack gets a working corpus in minutes instead of hours. Drop it for the full
set. Check the licence of anything you list.

**Curate this list; do not bulk-list.** Indexing is one model call per chunk, so cost
scales with total text rather than with file count. The one measurement in this repository
is the quickstart's bounded run — 80 curated pages in 8 minutes, 6 seconds a page — and
larger pages cost proportionally more. A list of a thousand documentation pages is a job to
project before starting, not to start and see; `winnow index` does exactly that and refuses
until you accept the number. The first version of the shipped pack listed several large documentation
repositories and produced 1,293 files — most of them API reference, which is high volume
and low claim density. "This function accepts these arguments" is not a claim anyone needs
a novelty verdict on, and it costs the same to extract as one that matters.

Prefer a few hundred claim-dense pages over thousands of reference pages. A good corpus is
selective, and `winnow index` will show you the projected cost before committing either way.

## Choosing min_corpus

The threshold below which Winnow refuses to judge novelty. Too low and early verdicts are
noise dressed as insight; too high and the tool stays silent for longer than it needs to.

25 is a reasonable default for a broad domain. Raise it for fields with a lot of
near-duplicate ground; lower it for narrow ones where a few dozen claims genuinely cover
most of what exists.

## Testing a pack

```bash
winnow packs                            # does it load?
winnow ingest <a link or file you know well>   # are the claims real claims?
```

Read the extracted claims before trusting any verdict built on them. If extraction is
producing vague or invented statements, no amount of clever judging downstream will fix it —
fix the prompt.
