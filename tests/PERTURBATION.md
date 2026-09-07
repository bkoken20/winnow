# Perturbation results

A green test proves nothing unless it could have gone red. Each behaviour below was
deliberately broken in the source, the guarding test was run, and the tree restored.

**26 behaviours, over five rounds.** Every mutation was detected except the three recorded
below as GREEN — two of which turned out to be faults in the mutation rather than gaps in
the tests, and one of which was a real gap that this process found.

Reproduce by applying the mutation, running the named test, and reverting.

| # | mutation applied | test | result |
|---|---|---|---|
| 1 | `num_ctx` removed from the request body | `test_generate_sets_num_ctx_in_options` | RED |
| 2 | `num_ctx` guard removed, silent truncation allowed | `test_generate_refuses_missing_context_window` | RED |
| 3 | `format: json` forced on every call, prose included | `test_describe_image_never_forces_json` | RED |
| 4 | retry loop reduced to a single attempt | `test_transient_status_is_retried` | RED |
| 5 | subtitle extensions added to `MEDIA_EXTENSIONS` | `test_subtitle_alone_is_not_treated_as_media` | RED |
| 6 | rolling-caption de-duplication removed | `test_rolling_captions_are_deduplicated` | RED |
| 7 | coverage check removed, thin corpus reports `new` | `test_thin_corpus_yields_unknown_not_new` | RED |
| 8 | hashing backend no longer marked untrustworthy | `test_hashing_backend_is_marked_untrustworthy` | RED |
| 9 | cost gate removed, long runs start unannounced | `test_long_run_is_refused_without_acceptance` | RED |
| 10 | cloud-judge egress warning silenced | `test_cloud_judge_produces_an_explicit_egress_warning` | RED |
| 11 | embedder silently falls back to hashing on failure | `test_ollama_embedder_does_not_silently_fall_back` | RED |

## Two defects this process actually found

Worth recording, because both were invisible to a passing suite.

**The retry tests were testing the fake, not the code.** The tests substituted `_post` —
the method that *contains* the retry loop — so replacing it deleted the behaviour under
test. They would have passed no matter what the retry logic did, or whether it existed. Fixed
by moving the seam down to `_fetch`, a single raw round trip, leaving the retry loop above it
where a test can exercise it.

**`ingest` crashed on its first real run while every unit test was green.** Verdicts carry a
foreign key to claims, and the code wrote the verdict before inserting the claim. Every
module was individually correct; the fault was in the ordering between them. Unit tests
cannot see that — `tests/test_pipeline.py` exists because of it.

## Round two — the cold-review fixes, and an adversarial pass over them

A fix nobody attacked is not verified. Each behaviour added or repaired after the
pre-publication review was broken again and its guarding test re-run.

| # | mutation applied | result |
|---|---|---|
| 12 | corpus left un-frozen during ingest (a talk becomes its own evidence) | RED |
| 13 | within-batch duplicate collapse removed (one point reported twice) | RED |
| 14 | frame path unwired again (documented feature with no caller) | RED |
| 15 | frames written back into the user's source folder | RED* |
| 16 | remote `ollama_host` reported as fully local | RED |
| 17 | unknown config keys silently dropped again | RED |

\* **This one was GREEN on the first attempt** — nothing tested where frame files landed,
so the fix was unverified. `test_ingest_writes_nothing_into_the_user_s_folder` exists
because the perturbation found that gap, not because anyone thought of it in advance.

### What the adversarial pass found in the review's own fixes

Four of the five defects it surfaced were introduced by the fixes made an hour earlier:

- Removing the study outputs (correct — they embedded third-party text) left **four
  experiment scripts reading files that no longer exist**. They crashed on the first line
  for anyone cloning the repository. They now fail with a message naming the script to run
  first.
- Frame extraction wrote JPEGs into the user's source folder.
- Up to 40 vision calls per ingest, several seconds each, on the one path with no cost
  gate — unannounced and unconfigurable. Now capped, configurable, and announced before it
  spends the time.
- Freezing the corpus fixed a talk being judged against itself, but made the same point
  appear **twice as `new`** when two passes found it. One finding is now reported once.
- The README claimed fourteen verified behaviours where this file documented eleven.

## Round three — attacking round two's repairs

| # | mutation applied | result |
|---|---|---|
| 18 | privacy check fails OPEN again (scheme-less host called local) | RED |
| 19 | a config setting shipped undocumented | RED |
| 20 | README's perturbation count desynced from this file | RED |
| 21 | an absolute machine path reintroduced into a tracked file | RED |
| 22 | a doc linking to a file that does not exist | RED |

Three of the four defects this round were again in the previous round's fixes:

- **`ollama_host = "ollama.example.com:11434"`** — an ordinary thing to write, just missing
  its scheme — parsed to no hostname, which the new local-check read as loopback. The tool
  then announced **"FULLY LOCAL. Nothing leaves this machine"** for a remote server. The
  check now fails closed: unreadable means not local, and the statement says how to fix it.
- Three config settings added in round two (`frame_every_seconds`, `max_frames`,
  `judge_num_ctx`) shipped **undocumented**, in the page whose completeness had been verified
  by hand an hour earlier. A check that runs only when someone remembers is not a check, so
  `tests/test_docs_match_code.py` now runs it every time.
- Library progress output went to **stdout**, which a caller parsing the tool's output would
  have to contend with. Moved to stderr.
- The studies **hard-coded three document filenames from the author's own corpus**, so every
  "reproduce with…" instruction in the experiment write-ups was impossible for anyone else:
  a forker pointing `WINNOW_NOTES` at their notes got a traceback naming a file they had
  never seen. They now take the three largest markdown files in the folder, whatever those
  are, and say that absolute numbers will differ while the comparisons hold.

## Round four — reading experiments/ top to bottom

Not a review of the code: a read of the folder's own write-ups, checking each claim against
what the scripts do. Four behaviours came out of it, each broken afterwards to confirm the
test fires alone.

| # | mutation applied | test | result |
|---|---|---|---|
| 23 | `applies_to` removed from the reference grades | `test_the_reference_grades_say_which_source_they_belong_to` | RED |
| 24 | the `WINNOW_REFERENCE_GRADES` gate removed | `test_the_strict_study_refuses_a_positional_join_it_cannot_verify` | RED |
| 25 | the grades file renamed after a human grader again | `test_the_grades_file_is_not_named_after_a_grader_it_did_not_have` | RED |
| 26 | a human attribution reinstated in a study script | `test_no_experiment_script_calls_its_reference_grades_human` | RED |

The defect behind 23-25: `strict_judge_study.py` joined the author's positionally-keyed
reference grades to whatever claims the current run extracted, and printed the agreement as
a finding. On anyone else's transcript that is verdict 7 of one video against claim 7 of
another, formatted exactly like the published number.

## Round five — reading tests/ top to bottom

No new behaviour, one widened: the link check of #22 named four documents by hand, and
five tracked markdown files escaped it — including every file written in round four. It now
discovers them from `git ls-files`, and asserts it found a plausible number before checking
any of them.

Re-verified after widening, by breaking a link in each of two files it did not previously
reach: `experiments/README.md` RED, `tests/PERTURBATION.md` RED. Deliberately not numbered
as new rows — the same guarantee covering more files is not a twenty-seventh guarantee, and
counting it as one would inflate the number in the README.

A structural sweep for tests that cannot fail — no assertion, an assertion on a literal, a
swallowed exception, an unconditional skip — found **none**. Seven tests have no `assert`
statement; all seven are negative controls ("this must not raise") or use `pytest.fail`,
which is the same thing written differently.

### A note on method, learned the expensive way

Reverting perturbation 26 with `git checkout -- <file>` reverted the *whole file*, including
uncommitted fixes that were not part of the mutation. Nothing was lost — they were re-applied
— but a perturbation must be undone by undoing the perturbation, not by resetting the file
it lives in. Commit first, or restore from a copy.

### Two mutations that came back GREEN, and what each meant

Both were faults in the *mutation*, not gaps in the tests — worth recording, because a
perturbation that fails to break the code proves nothing either way and it is tempting to
read it as a passing grade.

- Replacing `docs/PARAMETERS.md` in the README hit the link's display text, leaving the href
  valid. Mutating the href turned it red.
- Disabling the scheme check alone left a second layer intact (`""` no longer counts as
  loopback). Restoring both halves of the original defect turned it red.
