# Experiments

Every number quoted in Winnow's documentation was measured by something in this folder. The
three write-ups are the results; the scripts are how to get them again.

| write-up | question | headline |
|---|---|---|
| [CHUNK_SIZE.md](CHUNK_SIZE.md) | how much text should go into one extraction call? | far less than fits — 2,000 characters, not 120,000 |
| [TWO_PASS.md](TWO_PASS.md) | does a second pass over the same text pay for itself? | yes, and a third — but not the second pass that was expected |
| [CORRECTNESS.md](CORRECTNESS.md) | are the extracted claims faithful to the source? | 88% clean; the local judge that said 98% cannot be trusted |

Headline figures are also recorded, with how each was taken, in
[MEASUREMENTS.json](MEASUREMENTS.json), which a test checks the README against.

## Reproducing any of them

The scripts take no arguments. They read two paths from the environment, because a published
script with an absolute path from the author's machine makes every "reproduce with…"
instruction false for everyone else:

| variable | what it should point at |
|---|---|
| `WINNOW_NOTES` | a folder of markdown. The three largest files in it are used as the written-documentation sample. |
| `WINNOW_TRANSCRIPT` | a plain-text transcript — the spoken-source sample. |

```bash
# Linux / macOS
export WINNOW_NOTES=~/notes
export WINNOW_TRANSCRIPT=~/talk/transcript.txt

# Windows PowerShell
$env:WINNOW_NOTES = "C:\notes"
$env:WINNOW_TRANSCRIPT = "C:\talk\transcript.txt"
```

You also need Ollama running with the models in [MEASUREMENTS.json](MEASUREMENTS.json), plus
**`ollama pull gemma3:27b`** for the two correctness studies — it is the judge under test, and
it is deliberately a different family and size from the extractor, since a model grading its
own output shares its blind spots. It is not needed by Winnow itself and is not in the
project's install list.

**Your numbers will differ from the published ones**, and should. Different source material
means a different union of claims, and coverage is always a share of that union.

## What to run first

Later studies reuse earlier ones' stored claim texts rather than re-extracting, so they run
in an order. Each script says what to run first if you get it wrong, rather than dying on a
missing file:

```
chunk_size_study.py            WINNOW_NOTES                   ~20 min
  ├── chunk_size_small.py      WINNOW_NOTES + TRANSCRIPT      ~40 min
  └── two_pass_study.py        WINNOW_NOTES + TRANSCRIPT      ~37 min
        ├── third_pass_analysis.py    (no models, no env)     seconds
        ├── correctness_study.py      WINNOW_TRANSCRIPT       needs gemma3:27b
        └── strict_judge_study.py     WINNOW_TRANSCRIPT       needs gemma3:27b
              └── also needs correctness_study.py to have run
```

Times are from the studies' own recorded seconds, on the hardware in
[MEASUREMENTS.json](MEASUREMENTS.json). They are dominated by model throughput, so treat them
as an order of magnitude.

`third_pass_analysis.py` is the cheap one: it recomputes merges from stored claim texts and
calls no model at all.

## Why the result files are not committed

The studies write their outputs next to themselves — `chunk_size_results.json`,
`two_pass_results.json` and the rest. Those files embed **verbatim source text**, including
whatever third-party material you pointed the environment variables at, so they are
gitignored and never published. Only the write-ups and `MEASUREMENTS.json` are.

That has one consequence worth knowing: nothing here can be re-derived from the repository
alone. The tables are the record.

## What none of these measure

- **Whether a claim is true.** Faithfulness to the source is measured in CORRECTNESS.md;
  truth about the world is not measured anywhere, and Winnow does not attempt it.
- **Whether the claims are the *right* claims.** Coverage counts what was found against what
  the tested settings found between them — never against what exists.
- **More than one extraction model.** Everything here is `qwen2.5:14b-instruct` at
  temperature 0. A different model could reorder every conclusion.
