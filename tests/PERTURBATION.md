# Perturbation results

A green test proves nothing unless it could have gone red. Each behaviour below was
deliberately broken in the source, the guarding test was run, and the tree restored.

**175 behaviours, over thirty rounds.** Every mutation was detected except those recorded
below as GREEN — most of which turned out to be faults in the mutation rather than gaps in
the tests, and one of which was a real gap that this process found.

*(This line said "26 behaviours, over five rounds" while the tables below held 48 rows across
eleven rounds. An external review caught it. The count-sync test compares the README against
the ROW COUNT and passes — it had never been asked to read this document's own summary of
itself. A file about checking claims carried an unchecked one at the top.)*

Reproduce by applying the mutation, running the named test, and reverting.

## Round one — the enforced behaviours

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

## Round six — mutation sampling, which is the first round I did not choose

Every round above perturbed a behaviour I already suspected. That measures the tests I
thought to write, not the ones I did not. So: 224 mutable sites in `winnow/*.py`
(comparisons flipped, and/or swapped, booleans negated, integers incremented), **30 sampled
uniformly at random** with a fixed seed, applied one at a time with the suite re-run against
each.

**14 of 30 killed.** Of the 16 survivors, most were equivalent mutants — `flush=True` made
False, a 600-second timeout made 601, a JSON indent widened, `n=1` made `n=2` where only
`[0]` is read. Those change nothing a test could legitimately observe, and a suite is not
worse for ignoring them.

**Three were real, and all three are now covered:**

| # | mutation that survived | test added | result |
|---|---|---|---|
| 27 | `judge_location` dropped from the tier-1 stamp | `test_the_tier_one_stamp_records_every_field` | RED |
| 28 | `notes_path or environment` made `and` | `test_the_config_wins_over_the_environment` | RED |
| 29 | accepted budget converted at 61 seconds to the minute | `test_an_accepted_budget_means_exactly_that_many_minutes` | RED |

\#27 is the one worth reading twice. The README calls verdict stamping one of two rules the
tool will not bend, and `test_tier_one_records_the_judge_model` checked two of the seven
stamped fields. Flipping the tier check on the `judge_location` line alone survived the
entire suite — so a verdict produced by a **cloud** judge would record no location at all,
which is the field a reader would use to work out whether their claim text ever left the
machine. The README's own enumeration of the stamp had quietly dropped `tier` and
`judge_location` too; a test now checks the promise lists every field the dataclass has.

Two smaller ones are recorded but deliberately not fixed. `media.py` survived four mutations,
all inside the ffmpeg path this suite states plainly that it does not cover — a declared gap
is not a hidden one. And `pipeline.py`'s `digest_size=10` can change without any test
noticing, which would silently invalidate every existing corpus's source ids; that wants a
pinned golden value, and it is written here rather than fixed quietly.

**What the number is worth.** 14/30 is a wide interval on 30 draws, and the survivors were
classified by hand, by the person who wrote the tests. Read it as: the suite catches
roughly half of arbitrary damage, the half it misses is mostly cosmetic, and sampling found
three genuine holes in an afternoon that five rounds of choosing my own targets did not.

## Round seven — reading winnow/ top to bottom

The source itself, 2,615 lines. Four defects that change behaviour, and one class of stale
prose: the package still described the tool as it was before it took URLs.

| # | mutation applied | test | result |
|---|---|---|---|
| 30 | privacy statement claims nothing leaves the machine | `test_a_fully_local_statement_still_mentions_fetching` | RED |
| 31 | suggested budget rounded to nearest, not up | `test_the_budget_the_refusal_names_is_actually_accepted` | RED |
| 32 | `--with-video` satisfied by a captions-only cache | `test_asking_for_video_after_a_captions_only_fetch_actually_fetches_it` | RED |
| 33 | judge fallback narrowed back to unparseable JSON only | `test_valid_json_that_is_not_an_object_falls_back` | RED |
| 34 | `flags` taken as a list without checking it is one | `test_flags_that_are_not_a_list_do_not_become_one_flag_per_character` | RED |
| 35 | a file cited in Python source that does not exist | `test_files_cited_in_the_source_exist` | RED |

\#30 is the one to read twice. The README names `winnow status` as the authority on what
leaves your machine, and `egress_statement()` answered "FULLY LOCAL. Nothing leaves this
machine" while `winnow ingest <url>` shells out to yt-dlp. The README had already been
corrected for that exact sentence; the code it defers to had not.

**Two tests were holding the false claim in place.** They asserted the literal string
`"FULLY LOCAL"`, so the statement could not be made true without breaking them. The same
shape appeared again three commits later: a test pinning the word "unparseable" in the
judge's fallback rationale, which stopped the message widening to cover output that parses
but is the wrong shape. **A test that pins wording rather than a guarantee does not protect
the guarantee; it protects the wording, including when the wording is wrong.** Both now
assert the behaviour.

## Round eight — reading packs/ and scripts/

| # | mutation applied | test | result |
|---|---|---|---|
| 36 | `--limit 0` treated as no limit at all | `test_the_command_line_honours_a_limit_of_zero` | RED* |
| 37 | `--help` describing the replaced file-selection behaviour | `test_the_help_text_describes_what_the_code_does` | RED |
| 38 | the frame sentinel's uppercase requirement left undocumented | `test_the_pack_guide_says_the_sentinel_must_be_uppercase` | RED** |

\* **Each guard alone survives.** `--limit 0` was mishandled at two sites, and either one
being correct is sufficient: the outer check breaks before the first copy, the per-source
budget computes zero. Only reverting both reproduces the defect. Recorded because a
single-site mutation coming back green here looks like a test gap and is not one.

\** Removing only the bold lead-in from the guide survived, because "upper case" still stood
two lines below. Removing the whole paragraph is red. Third time in this repository that a
mutation which left the checked thing in place has read as a passing grade.

The packs folder was otherwise clean: the shipped pack's schema fields and its extraction
prompt ask for exactly the same six keys, and its own escape token is correctly filtered.
The defect was that neither of those couplings was written down anywhere, and one of them --
the token having to be capitals -- is a trap for pack authors, who are the people least able
to diagnose it.

## Round nine — reading the root files

Five tracked files. Two defects, and both were in a claim that had already been corrected
somewhere else in the same repository.

| # | mutation applied | test | result |
|---|---|---|---|
| 39 | README's Privacy section answers "By default: nothing" | `test_the_readme_privacy_section_does_not_say_nothing_leaves` | RED |
| 40 | README and `egress_statement()` name different network calls | `test_the_readme_agrees_with_the_code_about_what_leaves` | RED |
| 41 | `pyflakes` dropped from the `dev` extra | `test_the_dev_extra_installs_what_the_suite_needs` | RED |
| 42 | a module using syntax newer than the declared Python floor | `test_the_declared_python_floor_is_one_this_code_could_run_on` | RED |

\#39 is the third appearance of one claim. `egress_statement()` said "Nothing leaves this
machine" (round seven). The README's opening said it too, and was fixed weeks earlier. The
section actually **headed Privacy** still said it — under the heading a reader goes to for
precisely this question. Fixing one instance of a claim and leaving another in the same
document is how this survives, so the check reads the whole SECTION rather than a sentence
someone remembered to change, and #40 asserts the two places describe the same network call.

\#41 is a missing dependency that degrades a check into a **skip**. `pip install -e .[dev]`
installed only pytest, so `test_no_undefined_names_or_unused_imports` — the check that exists
because three scripts once shipped with a syntax error — was skipped by its own `skipif`,
silently, as one `s` in a `-q` run, with the suite still green. A dependency whose absence
makes a check vanish is worse than one whose absence makes it fail.

### A mutation that came back GREEN, correctly

Lowering `requires-python` from `>=3.10` to `>=3.9` leaves the suite green, and that is the
right answer rather than a gap. Every union type in the package is an annotation, and every
module using one defers annotations, so nothing here actually requires 3.10. The floor is
conservative, not wrong. Recorded because a green mutation is otherwise indistinguishable
from a missing test, and this one was checked rather than assumed.

The other three root files were clean: `LICENSE` is unmodified MIT, `.gitignore` covers every
generated artefact (verified with `git check-ignore` in round four), and `requirements.txt`
is now the thing `pyproject.toml` agrees with rather than contradicts.

## Round ten — one class of defect, across every file at once

The first round organised by DEFECT rather than by folder, and the reason is worth recording:
the README was read top to bottom, declared checked, and then amended in six later commits.
Five of those six defects were claims about OTHER files — a figure whose table lives in
`experiments/`, a field list that lives in `models.py`, a count that lives in this file.
**Reading a document in isolation can find internal inconsistency and nothing else.** It can
never establish that a claim about code is true, so "I read it" was never capable of
producing "it is correct", and reading it first guaranteed the rest would surface later.

So instead of reading anything again, one question was asked of every file: *does each
number appear in the record that exists to hold numbers?*

| # | mutation applied | test | result |
|---|---|---|---|
| 43 | a quantity in the README with no entry in the record | `test_every_measured_quantity_in_the_readme_is_recorded` | RED |
| 44 | the same, in `docs/` | `test_every_measured_quantity_in_the_docs_is_recorded` | RED |
| 45 | a projected figure quoted with no mark of a projection | `test_a_projection_is_never_quoted_as_a_measurement` | RED |

**What the question found.** "337 files, about 3.5 hours" was in the Quickstart, telling a
reader whether to commit to an overnight job, and `docs/DOMAIN_PACKS.md` called it
*Measured:*. It was arithmetic: a file count times a per-page ESTIMATE, relabelled. The one
real indexing measurement — 80 files in 479s — implies about 34 minutes for 337, six times
smaller. Withdrawn, with the withdrawal recorded so the absence is visible.

Then the same shape again in `docs/`: `TWO_PASS.md` states plainly that its index hours are
projected and not a measured run, and those hours were quoted in five other files with no
caveat at all. A caveat written once stays where it was written. It travels now, and a test
makes it travel.

**The mechanism, three times over.** The figures check listed THREE numbers by hand and
called itself a spot-check; a spot-check of three cannot catch the fourth. That is the third
hardcoded list in this repository to *be* the defect, after the link check that named four
documents while five escaped and the number-word map that stopped at thirty. Every one of
them now derives its list instead of holding one.

### Attacking round ten found two faults in round ten's own checks

- **Recording a withdrawal made the withdrawn figure pass.** The block that withdraws "337
  files, about 3.5 hours" quotes it in order to withdraw it, so the number was present in
  the record and the check went green on re-adding it to the README. Blocks marked NOT
  MEASURED are excluded from the haystack now.
- **The projection check passed for the wrong reason at two of four sites.** It examined the
  enclosing paragraph, and a markdown table is one paragraph — so "The projection accounts
  for it" in an unrelated row satisfied a different row, as did "NOT measured", written
  about frame sampling, for a claim about index hours in `config.py`. It checks a
  240-character window around each occurrence now. Re-attacked: three of four red, and the
  fourth survives correctly because that caveat genuinely sits two lines below its figure.

Neither would have been found by running the check. Both were found by trying to defeat it.

## Round eleven — running it against real models, which reading never substituted for

Ten rounds of reading, 321 offline tests, a clean-clone check, and the tool had not been run
end to end against a real model since the code started changing. The suite is entirely
stubbed: it proves the stubs are satisfied, not that an ingest works.

One real run — cached video, 383-claim corpus, real Ollama, 5 minutes — and:

**60 of 74 claims from a video ALREADY IN THE CORPUS came back `NEW`.**

| # | mutation applied | test | result |
|---|---|---|---|
| 46 | re-ingested material judged without regard to being stored | `test_reingesting_the_same_material_does_not_report_it_as_new` | RED (30/30) |
| 47 | the verdict not saying why it is known | `test_a_claim_already_in_the_corpus_says_so` | RED |
| 48 | everything forced to `known` | `test_genuinely_new_material_is_still_new` | guard, green throughout |

**The cause is a correct rule in the wrong place.** `similarity_search` excludes the claim
being judged, because a claim is not evidence about itself — right, and necessary for
`rejudge`. But re-ingesting produces the SAME claim ids (a hash of pack, source and text), so
the second time round each claim's nearest neighbour is its own stored copy, and excluding it
leaves only weaker matches. The tool then announced as a discovery something it had already
read. The corpus IS what the reader knows; if a claim is in it, no threshold should be
consulted to decide otherwise.

Verified on the same real run that exposed it: 60 new / 12 variant / 2 known became 0 new /
6 variant / 62 known.

### The fixture masked the defect it was written for

The first version of the red test PASSED. It generated thirty variations of one sentence, and
under the hashing embedder those score highly against each other — so a sibling stood in for
the excluded self and the verdict read `known` for the wrong reason. The real corpus holds
mutually DISSIMILAR claims, which is exactly the condition that produces the fault. Rewritten
with unrelated subjects: 30 of 30 red.

**A fixture that cannot reproduce the defect is a test that cannot fail**, and it looked like
a passing grade for the code.

### Two ways a perturbation result can be worthless, both hit in one sitting

Recorded here because both produce a confident answer that means nothing, and neither is
visible in the output.

**A mutation that does not land.** `str.replace` returns the string unchanged when its
anchor does not match, so a perturbation script with no assertion happily writes the
ORIGINAL file back, runs the suite against it, and reports SURVIVED. The test was never
challenged. Every perturbation must assert that the file actually changed and that the
defect is present in the new text.

**A perturbation run against an already-red test.** If the suite is failing for any other
reason when the mutation is applied, the run reports KILLED whichever way the mutation went.
The result is indistinguishable from success. Confirm green BEFORE mutating, every time.

Both happened while fixing review item 2: the first perturbation reported KILLED because the
test was already failing on unrelated prose, and the second reported SURVIVED because the
anchor never matched. Two results, no evidence, and only re-running properly showed the
check does work.

### Two mutations that came back GREEN, and what each meant

Both were faults in the *mutation*, not gaps in the tests — worth recording, because a
perturbation that fails to break the code proves nothing either way and it is tempting to
read it as a passing grade.

- Replacing `docs/PARAMETERS.md` in the README hit the link's display text, leaving the href
  valid. Mutating the href turned it red.
- Disabling the scheme check alone left a second layer intact (`""` no longer counts as
  loopback). Restoring both halves of the original defect turned it red.

## Round twelve — an external review, and the rows three fixes never got

A second reviewing model read the repository for publication readiness. Its findings are
being worked one at a time; this round records the perturbations for the four fixed so far.

Rows 49-51 belong to fixes that shipped in earlier commits. They were perturbed at the time
and never written down, so the record's own count stopped at eleven rounds while the code
moved on. Their mutations were re-applied and re-run before these lines were written -- a
row recalled is not a row verified.

Rows 52-63 are one review item: **predictable input mistakes answered with a traceback.**
A pack manifest with no `name` gave `KeyError: 'name'`; a `winnow.json` holding a JSON array
gave `TypeError: 'int' object is not iterable`; `text_num_ctx: 10` and
`embed_backend: "cloud"` both gave a bare `ValueError`. The handler for a corrupt corpus
re-read the configuration to name the corpus path, so a second failure there replaced the
one-line database error with a chained traceback -- the handler defeating its own purpose.

| # | mutation applied | test | result |
|---|---|---|---|
| 49 | the caption fallback re-requesting the video | `test_fallback_does_not_refetch_video.py` | RED (3 of 4) |
| 50 | the already-known verdict reporting a sentinel instead of a similarity | `test_reingest_similarity_is_real.py` | RED (2 of 4) |
| 51 | identity and memory using different spellings of one path | `test_source_paths_are_normalised.py` | RED (3 of 4) |
| 52 | a pack manifest with no `name` accepted | `test_a_nameless_pack_is_an_invalid_pack` | RED |
| 53 | a pack manifest that is not a JSON object accepted | `test_a_manifest_that_is_not_an_object_is_an_invalid_pack` | RED |
| 54 | a `winnow.json` that is not a JSON object accepted | `test_a_config_that_is_not_an_object_is_refused` | RED |
| 55 | an unknown `embed_backend` not refused at load | `test_status_does_not_describe_a_backend_that_does_not_exist` | RED |
| 56 | `is_fully_local` back to the one spelling `!= "cloud"` | `test_the_local_check_covers_every_unknown_backend_not_one_spelling` | RED |
| 57 | the privacy statement describing a backend that cannot be built | `test_a_directly_built_config_is_not_local_on_an_unknown_backend` | RED |
| 58 | `EMBED_BACKENDS` naming a backend the dispatch has no branch for | `test_every_named_backend_can_actually_be_built` | RED |
| 59 | an unusable `text_num_ctx` raising a bare `ValueError` | `test_an_unusable_context_window_is_refused_before_any_work` | RED |
| 60 | an unknown backend raising a bare `ValueError` | `test_an_unnamed_backend_is_a_configuration_error` | RED |
| 61 | the corpus created before the configuration is checked | `test_an_unusable_context_window_is_refused_before_any_work` | RED |
| 62 | the database handler re-reading a configuration that can fail | `test_the_database_handler_survives_an_unreadable_config` | RED |
| 63 | no exit code for a setting whose value cannot be used | `test_the_cli_reports_a_misshapen_config_as_code_two` | RED |

### The suite was red for three commits and I reported it passing

The tracked-files guard forbids absolute machine paths in tracked files. Fixing row 51 meant
writing a docstring that *explains* a path-spelling defect, and the example I wrote was
drive-shaped, so the guard fired on my own prose. I reworded the copy in `winnow/pipeline.py`
and left the identical wording in the test file -- and the suite has been red from that
commit until this one, while the closing report said 478 tests passing.

The rule that catches this is already written down (*gate the commit on the suite's exit
code, never on a line of its output*) and it was followed; the failure was reading the tail
of one run and not re-reading it after the last edit. **Green is a fact about the tree as it
stands now, not a fact about the tree twenty minutes ago.**

### One guard, one test

Row 61 -- the corpus must not be created before the configuration is refused -- is caught by
exactly one test, and not the one I expected. `test_an_unknown_embedding_backend_is_refused`
makes the same assertion but cannot detect the ordering, because an unknown backend is now
refused when the configuration is *read*, long before `Pipeline.build` runs. Two guards at
different depths, and only the deeper mistake exercises the deeper one.

## Round thirteen — which file a folder is actually read from

A folder can hold captions Winnow fetched, a machine translation of them, and a transcript
the user wrote. It picked one silently, and the order was undocumented and untested.

The order was also **backwards against Winnow's own instructions**. When a video has no
usable captions the tool says: *"produce a transcript yourself and place it in a folder as
transcript.txt"*. Do that in a folder that already holds a `.vtt` — which is every folder
where the captions are the problem — and the file you just wrote was ignored without a word.

Among subtitles the choice was `sorted()`, so `video.en-orig.vtt` beat `video.en.vtt` only
because `-` precedes `.` in ASCII: the right answer, for a reason that would stop holding the
day a file was named differently. This repository's own cache holds both files.

| # | mutation applied | test | result |
|---|---|---|---|
| 64 | fetched captions beating a hand-placed transcript | `test_a_hand_written_transcript_beats_fetched_captions` | RED (5 across the suite) |
| 65 | the subtitle choice back to `sorted()[0]` | `test_the_original_caption_track_beats_the_translation` | RED |
| 66 | the original marker matched anywhere in the name | `test_orig_must_be_the_language_tag_not_a_word_in_the_title` | RED |
| 67 | the marker spelled `-original` rather than what yt-dlp writes | `test_the_original_caption_track_beats_the_translation` | RED |
| 68 | the run not naming the file it read | `test_ingest_says_which_file_it_read` | RED |
| 69 | a documentation link with its target on the next line | `test_no_link_is_split_across_two_lines` | RED |
| 70 | a documentation anchor with no such heading | `test_anchor_links_point_at_a_real_heading` | RED |
| 71 | a documentation link to a file that does not exist | `test_internal_links_resolve` | RED |
| 72 | code spans scanned as if they were prose | `test_prose_keeps_the_links_it_is_meant_to_check` | RED (3) |

### The link check could not see the links I was writing

Rows 69 and 70 are not from the review. They come from attacking this item's own fix: the
documentation it added contained a link split across two lines — markdown needs `](`
adjacent, so it rendered as literal brackets — and the suite stayed green.

`test_internal_links_resolve` matches `](` followed by `[^)#]+`, which requires at least one
character before any `#`. An anchor-only link is `](#slug)`, so the pattern matches **nothing
at all** and every in-page link in the repository was unchecked. A split link is not a link
by then, so nothing looked at it either.

**A check written against the links that existed when it was written.** Both new checks are
parametrised over every tracked markdown file, like the one they sit beside.

Then the new checks fired on this very document. Writing the round above put the literal
pattern for a markdown link into a code span, and all three link checks read it as a link.
The temptation is to reword the sentence -- and that is the trap: markdown creates no link
inside a code span or a fenced block, so the checks were reporting something that cannot
happen, and a check you write around gets written around again by deleting whatever sentence
annoys it next. The checks now scan PROSE: the document with fenced blocks and inline code
removed. Row 72 is the guard on that, because a stripper that removed too much would make
every link test pass by having nothing left to check.

Rows 69 and 70 were verified BEFORE that change and re-run after it. A perturbation result
describes the code that was standing when it ran, and that code had been replaced.

### What decided the order, since both directions are defensible

Not which file is "better" — which mistake the user can undo. A `transcript.txt` that wins
when it should not is a file they created and can rename. A `.vtt` that wins when it should
not sits in a cache folder named after a hash of the URL, which nothing in the documentation
tells them to open. Only one of those is recoverable with what they already know.

The second half is that the run now prints the file it read, so the choice is visible rather
than inferred from the claims that come out.

## Round fourteen — `--config`, and a fix that reintroduced its own bug

`winnow ingest URL --config x.json` failed with *"unrecognized arguments: --config
x.json"* -- a message that names what it rejected and not the one thing that helps, which is
that the flag has to move to the left of the subcommand. That is the spelling people type:
the subcommand is what they came to run and the configuration is an afterthought.

| # | mutation applied | test | result |
|---|---|---|---|
| 73 | the flag not accepted before the subcommand | `test_the_flag_is_still_accepted_before_the_subcommand` | RED (7) |
| 74 | the subcommand copy given an ordinary default | `test_the_flag_is_still_accepted_before_the_subcommand` | RED (5) |
| 75 | `ingest` not accepting the flag after the command | `test_the_flag_is_accepted_after_the_subcommand` | RED |
| 76 | `packs` not accepting the flag after the command | `test_the_flag_is_accepted_after_the_subcommand` | RED |

### The guard test caught the fix

Row 74 is not a hypothetical. The first version of the fix added the option to every
subparser with `default=argparse.SUPPRESS`, so that a subcommand copy could not overwrite a
value the top-level form had already parsed -- and then called
`parser.set_defaults(config=None)` to supply the default in one place.

**`parents=[...]` shares action objects; it does not copy them.** And `set_defaults` walks
`self._actions` assigning `action.default`. So one call on the top-level parser rewrote the
default on the very action every subcommand was using, switched the suppression off
everywhere, and restored the exact fault being fixed -- in the opposite direction. Five tests
went red naming it, all of them the *guard* half of the pair: `winnow --config x.json status`
had stopped working while the new spelling worked fine.

Written before the fix, the guard existed only because the failure mode was obvious in the
abstract. It then happened.

## Round fifteen — what a listing page would say, and whether it is true

`pyproject.toml` carried a name, a version and a description. No classifiers, no keywords, a
`license = {file = "LICENSE"}` table that setuptools 77 deprecates, and two independently
declared versions -- `winnow/__init__.py` and `pyproject.toml` -- that nothing compared.

| # | mutation applied | test | result |
|---|---|---|---|
| 77 | the two declared versions disagreeing | `test_the_two_declared_versions_agree` | RED (2) |
| 78 | the licence back to the deprecated table form | `test_the_licence_is_declared_the_modern_way` | RED |
| 79 | `license-files` emptied | `test_the_licence_is_declared_the_modern_way` | RED |
| 80 | a classifier claiming a Python below `requires-python` | `test_there_are_classifiers_and_they_do_not_contradict_requires_python` | RED |
| 81 | a placeholder left in the metadata | `test_no_placeholder_survives_into_the_metadata` | RED |
| 82 | `Typing :: Typed` claimed with no `py.typed` marker | `test_a_typed_claim_ships_the_marker_that_makes_it_true` | RED |

Row 82 is a classifier I added in this round and removed in the same one. `Typing :: Typed`
tells a type checker to read the package's annotations; what a checker actually reads is
`winnow/py.typed`, which does not exist. The classifier is dropped, and the test now ties the
two together in both directions, so neither can arrive alone.

Row 81 SURVIVED on its first run. The check was `<[a-z-]+>|YOUR[_ ]|TODO|FIXME` and the
mutation inserted `<your keyword here>` -- no spaces allowed by the pattern, and `YOUR` only
in capitals. **A check that recognises the two spellings its author thought of**, which is
the same fault as a link check that only sees the links that existed when it was written.
Widened, then RED.

### A third way a perturbation result can be worthless: stale bytecode

The two already recorded are a mutation that never lands and a run against an already-red
suite. This one is worse, because the file on disk is correct while the code being executed
is not.

Mutating `__version__ = "0.1.0"` to `"0.2.0"` and restoring it left this:

```
source mtime 1788931359.44  size 613
pyc records  1788931359     size 613
imported version: 0.2.0        <- the file on disk said 0.1.0
```

Python validates a cached `.pyc` against the source's mtime **in whole seconds** and its
size. The mutation and the restore happened inside one second, and `"0.2.0"` is the same
length as `"0.1.0"`, so the cache compiled from the mutated source looked current. The next
run reported a failure for a mutation that had already been reverted -- and with the polarity
reversed it would have reported SURVIVED for a guard that works perfectly.

Any same-length mutation is exposed: a digit, a comparison operator, a swapped identifier of
equal length. **The harness now deletes the cached bytecode for every file it writes**, on
the way in and on the way out.

### Review item 14 now lives in the suite

The README still says `git clone https://github.com/<you>/winnow.git`, and the review's own
instruction is not to invent a destination to make the placeholder go away. So
`test_the_readme_clone_url_is_real` is a **strict** xfail: it records that the install
instructions cannot work for any reader, and the day a real repository URL replaces the
placeholder the test passes, the strict marker turns that into a failure, and the marker
comes off. A blocker in the suite rather than in a note.

## Round sixteen — the privacy section named one outbound path of five

The README pointed at `winnow status` as the authority and then summarised it, and the
summary listed yt-dlp alone. Four more exist: every model call goes to `ollama_host` (local
only because it defaults to localhost), `scripts/fetch_starter_corpus.py` runs `git clone`,
and both documented `pip install` lines contact a package index.

`judge_location` was the same fault as `embed_backend: "cloud"` from round twelve. The
statement described what a cloud judge would transmit; the judge is
`OllamaClient(host=ollama_host)` whatever the setting says, so it routes nothing. Worse, it
was compared with `!= "cloud"`, so `"cloutd"`, `"Cloud"` and `""` all read as fully local --
**a privacy check failing OPEN**, which the same file's `host_is_local` explicitly refuses to
do three functions above it.

| # | mutation applied | test | result |
|---|---|---|---|
| 83 | an unknown `judge_location` accepted at load | `test_an_unknown_judge_location_is_refused` | RED |
| 84 | the local check back to `!= "cloud"` | `test_a_misspelt_judge_location_is_not_treated_as_local` | RED (2) |
| 85 | no reason written for an unreadable `judge_location` | `test_the_reason_names_the_setting_and_the_value_that_is_wrong` | RED |
| 86 | a NOT LOCAL verdict rendering as a bare full stop | `test_a_verdict_with_no_written_reason_still_explains_itself` | RED |
| 87 | the `git clone` unnamed in the privacy section | `test_the_privacy_section_names_every_outbound_path` | RED |
| 88 | the package index unnamed | `test_the_privacy_section_covers_the_package_index` | RED |
| 89 | `ollama_host` unnamed as what decides the destination | `test_the_privacy_section_names_every_outbound_path` | RED (2) |
| 90 | a file dropped from the outbound list | `test_the_list_of_outbound_paths_is_complete` | RED |

### Two guards, each passing the other's tests

Rows 85 and 86 both SURVIVED first. Making `is_fully_local` fail closed created a case with
no sentence written for it, so the statement came out as **"NOT FULLY LOCAL. ."** -- a
headline, a full stop, and nothing to act on. The repair was a specific reason for that case
AND a catch-all for any future one, and then neither could be tested: remove the specific
branch and the catch-all still produces a long sentence that happens to name three settings;
remove the catch-all and no case reaches it.

**Two guards where each hides the other's absence is one guard, tested twice.** Now the
reason must name the offending setting *and its value*, which the catch-all cannot do, and
the catch-all is tested on its own terms by forcing the verdict false with no branch to
explain it.

### A mutation that changes the file without removing the behaviour

Rows 88 and 89 also survived first. Both phrases appear in more than one row of the new
table, so deleting one occurrence left the section still telling the reader the true thing --
the check was right to stay green. The perturbation, not the check, was the thing that had
failed. **A mutation has to remove the behaviour, not an instance of it**, which is the same
lesson as `str.replace` writing the original file back, arriving from the other direction.

## Round seventeen — nothing had ever run this on a machine that is not mine

Sixteen rounds, five hundred tests, and every one of them on one Windows box with one Python.
`requires-python = ">=3.10"` was a promise nothing could keep, and a test in
`test_packaging_metadata.py` says so in its own docstring: *"This does NOT prove the code
runs on 3.10 -- only an interpreter can do that, and there is not one here."*

A workflow file is itself a claim, so the tests below check what can be checked from here:
that it parses, that its matrix contains the floor `pyproject.toml` promises, that it runs
the same suite the README tells a contributor to run, and that its actions are pinned rather
than following a branch someone else can move.

| # | mutation applied | test | result |
|---|---|---|---|
| 91 | the ship-detector no longer recognising a corpus database | `test_the_detector_finds_what_it_is_looking_for` | RED |
| 92 | the ship-detector no longer recognising stale build output | `test_the_detector_finds_what_it_is_looking_for` | RED |
| 93 | the release procedure replaced by `tar czf . ` | `test_the_release_procedure_is_written_down` | RED |
| 94 | CI dropping the oldest Python the package claims | `test_it_tests_the_oldest_python_the_package_claims` | RED (2) |
| 95 | CI not running pyflakes | `test_it_runs_the_linter_that_catches_undefined_names` | RED |
| 96 | CI not running the suite | `test_it_runs_the_suite_the_readme_documents` | RED |
| 97 | CI not checking the built metadata | `test_it_builds_the_distribution_it_publishes_metadata_for` | RED |
| 98 | an action following `@main` instead of a pinned major | `test_every_action_is_pinned_to_a_major_version` | RED |
| 99 | `OSError` no longer answered with an exit code | `test_an_operating_system_error_is_a_sentence_not_a_traceback` | RED (2) |

### Row 99 is what thinking about Linux found before Linux did

`winnow --config <a directory>` reads a directory. Windows raises `PermissionError`, which
`_run` catches and turns into a one-line message and exit 2. Linux and macOS raise
`IsADirectoryError`, which nothing caught -- so the same typo is a tidy answer on the machine
this was written on and a traceback on the two it was not. A full disk (`ENOSPC`) had no
handler anywhere.

`FileNotFoundError` and `PermissionError` were handled because they are the two errors
**this machine** produces for the mistakes I make. The whole class is `OSError`, and the test
raises the errors directly rather than creating a directory, so it is red on every platform
rather than only where the bug shows.

### What the ship test is actually for

The working directory holds a 2.1 MB corpus with 383 claims and absolute local paths, a local
`winnow.json`, fetched captions, stale `build/` output and an `egg-info` carrying an older
README. All of it gitignored; none of it tracked; the repository is clean. The failure mode
is not a bad commit -- it is publishing by **copying the folder**, at which point every one of
them ships. So the check is on `git archive HEAD`, which is what a stranger would actually
receive, and it runs both ways: nothing local in it, and it is still recognisably the project.

## Round eighteen — a setting of the wrong type, and the first round with a code walk

`Config.load` checked two settings by name and nothing else. Every other value went into the
dataclass exactly as JSON produced it and failed later, in the middle of a run, as a Python
error. Ten were reproduced against the real CLI with Ollama running:

```
text_num_ctx: "32768"       TypeError: unsupported operand type(s) for -: 'str' and 'int'
text_num_ctx: null          TypeError: unsupported operand type(s) for -: 'NoneType' and 'int'
chunk_chars: "2000"         TypeError: '<' not supported between instances of 'int' and 'str'
duplicate_threshold: "0.9"  TypeError: '<=' not supported between 'str' and 'int'
corpus_path / packs_root / notes_path: 5   TypeError: argument should be a str or PathLike
pack: 5                     TypeError: unsupported operand type(s) for /: 'WindowsPath' and 'int'
ollama_host: 5              AttributeError: 'int' object has no attribute 'decode'
index_extra_passes: 1000    TypeError: 'int' object is not iterable
```

Four of those the review did not list; one it did list -- `judge_num_ctx: 0` -- could not be
reproduced here, and is recorded as unreproduced rather than inherited. `duplicate_threshold:
5.0` was worse than any of them: accepted in silence, and since no cosine reaches 5, nothing
is ever a duplicate and the output does not say the check is off.

The types are read from the annotations the dataclass already carries, so a setting added
later is checked the day it appears rather than the day someone remembers a table. Only
ranges -- "this one is a size", "this one is a similarity" -- need naming by hand.

| # | mutation applied | test | result |
|---|---|---|---|
| 100 | the validator not called at all | `test_a_value_of_the_wrong_type_is_refused` | RED (45) |
| 101 | `true` counting as a whole number | `test_true_is_not_a_number` | RED |
| 102 | `true` counting as a similarity | `test_true_is_not_a_similarity_either` | RED |
| 103 | a whole number refused where a similarity is expected | `test_a_whole_number_is_a_valid_similarity` | RED |
| 104 | a list's entries unchecked | `test_a_list_of_the_wrong_thing_is_refused` | RED (2) |
| 105 | a size of zero accepted | `test_a_size_of_zero_is_refused` | RED (2) |
| 106 | a similarity outside 0-1 accepted | `test_a_similarity_threshold_outside_zero_to_one_is_refused` | RED |
| 107 | zero itself no longer too small | `test_a_size_of_zero_is_refused` | RED (6) |
| 108 | a similarity ABOVE one accepted | `test_a_similarity_threshold_outside_zero_to_one_is_refused` | RED |
| 109 | the declared kind not read from the annotation | `test_a_value_of_the_wrong_type_is_refused` | RED (38) |
| 110 | a range-checked setting that is not a number | `test_every_range_checked_setting_is_a_number` | RED (49) |

### Row 110 came from the code walk, not from the tests

The suite was green -- 636 tests -- and the fix still carried the bug it was fixing. Walking
the validator with real values:

```
Lines 118 and 123 compare `value` with 0 WITHOUT knowing it is a number.
  with the type check present:  refused at config.py:106 (never reaches 118)
  with the type check disabled: TypeError: '<=' not supported between 'str' and 'int'
```

`if name in POSITIVE_SETTINGS and value <= 0` is safe **only** because the type check above
has already rejected a non-number for every name in that tuple -- which holds only while
every name in it happens to be an `int` field. Nothing enforced that. Change `max_frames` to
a string one day and the comparison raises the very traceback the validator exists to
prevent, thrown by the validator.

The tuples cannot be derived: nothing in `int` says "this one is a size". So the coupling is
real, and the instrument is a test that names it.

**No red test would have found this**, because the invariant holds today. It came from
opening the file and reading what the statements do with values, which is what CHARTER 67
added to the method on the day this round was worked.

### The count outgrew its own spelling table, for the third time

This round takes the record to 110 rows, and `test_docs_match_code._number_words(1, 99)`
stops at ninety-nine. Its docstring already records the hardcoded map it replaced running
out twice, and that when it does, the test fails on its "no count found" branch --
**reporting that the README states no count at all, when it states one the test cannot
spell.** Generating the words moved the ceiling; it did not remove it. A numeral now counts
as a stated count, which has no ceiling and leaves the guarantee -- that the README's number
equals the table's row count -- exactly as it was.

## Round nineteen — the gate measured an empty file and let the run through

Sampling the MEDIAN file is the right instinct: real notes folders spread over an order of
magnitude, and timing an arbitrary file projects the whole run badly. But when more than half
the files are empty, the median IS empty, and two things go wrong at once -- timing it
measures almost nothing, and `sample_bytes == 0` sends the projection down the file-count
path, which multiplies that same near-zero unit.

**Measured on the reported shape** -- twelve files, seven empty, 41,600 bytes of real text:

```
before: unit=0.00021 s x 12 units                      ->    0.0025 s
after : 8000 B in 0.391 s = 20,480 B/s over 40,000 B   ->    1.9531 s
ratio :                                                       775x
```

The gate is satisfied by a number describing none of the work, and the README's promise --
"indexes one file, times it, projects the whole run, and will not proceed until you accept a
budget that covers it" -- is broken by the most ordinary folder there is. `touch` leaves
empty files, an interrupted export leaves them, and a notes folder grown over years is full
of them.

| # | mutation applied | test | result |
|---|---|---|---|
| 111 | empty files back in the sample | `test_the_sampled_file_has_something_in_it` | RED (4) |
| 112 | the sample taken as the largest, not the median | `test_a_normal_folder_still_samples_the_median` | RED |
| 113 | the all-empty folder left with no sample | `test_an_entirely_empty_folder_is_honest_about_it` | RED (4) |
| 114 | a projection that cannot describe its run allowed | `test_a_projection_cannot_claim_bytes_it_did_not_sample` | RED |
| 115 | the volume path abandoned when bytes are known | `test_the_projection_still_scales_by_volume` | RED (2) |

### Row 112 survived first, and the fixture was why

`sorted(..., reverse=True)` -- sample the LARGEST file rather than the median -- left the
suite green. The fixture had five files, and **the middle index of an odd-length list is the
middle whichever way it is sorted**. The assertion could not distinguish the two orders it
was written to distinguish. Six files, one of them a 20 KB monster, and it goes red.

A symmetric fixture is a fixture that cannot fail, in the same family as the thirty
near-identical sentences in round eleven.

### What the walk added

The suite was green at 649 tests before the walk. Running the changed lines over seven real
folder shapes showed the sampling behaves, and showed something the tests never look at:
`total_bytes`, the emptiness filter and the sort key each called `p.stat()` separately, and
`sample_bytes` read it a fourth time. On a folder something else is writing to, those four
reads can see four different sizes of the same file -- the total disagreeing with the sort
that chose the sample. One snapshot now, read once.

No test asserts that, and no reasonable one could: it is a consistency property of a
directory being mutated underneath us. It came from reading the statements.

### The second half of the fix is a state that cannot exist

`sample_bytes == 0` with `total_bytes > 0` says there is volume to process and throughput was
never measured -- and `extraction_seconds` then reverts to unit x count without saying so.
`Projection` refuses that combination at construction, so the fallback cannot be reached
silently by any future caller, rather than the pipeline being trusted to remember.

## Round twenty — a privacy statement about a transport that does not exist

With `judge_location: "cloud"`, a judge model set and `ollama_host` at its default
localhost, `winnow status` printed:

```
NOT FULLY LOCAL. a cloud judge ('qwen2.5:14b-instruct') is declared, so the text of each
claim judged, plus the most similar claims from your corpus, is sent to it.
```

Nothing is sent to anything. The judge is `OllamaClient(host=ollama_host)`, the host is this
machine, and Winnow has no cloud client of any kind. False, in the alarming direction, in the
one place the README names as the authority — which is how people learn to skip the warning
that matters. The README then repeated it one sentence further on: *"Judge location is the
one that matters most later: it says whether the claim text was sent anywhere."* It does not.

`judge_location` is worth keeping for exactly the case that makes the old sentence wrong: an
`ollama_host` that looks like loopback and forwards elsewhere — an SSH tunnel, or the proxy
variables `urllib` honours — which only the person running it knows about.

| # | mutation applied | test | result |
|---|---|---|---|
| 116 | the statement claiming a cloud transport again | `test_a_declared_cloud_judge_on_a_local_host_does_not_claim_a_transport` | RED (2) |
| 117 | the declaration ignored, address only | `test_a_declared_tunnel_is_recorded_as_having_left` | RED (2) |
| 118 | the answer recorded only at tier 1 | `test_tier_zero_keeps_the_declaration_that_tier_zero_erases` | RED (2) |
| 119 | the answer not recorded at all | `test_the_stamp_records_whether_the_material_stayed_here` | RED (5) |
| 120 | an unrecorded answer defaulting to "it stayed" | `test_a_stamp_from_an_older_corpus_still_loads` | RED |
| 121 | a stamped field missing from the README's list | `test_the_readme_lists_every_stamped_field` | RED |

### The walk found the hole in my own fix, an hour after I opened it

The first version added `host_is_local` to the stamp — the address, which is what actually
decides the transport. 661 tests green. Walking every combination of the three settings that
reach it:

```
host        declared  tier  judge_location  host_is_local
localhost   cloud     0     ''              True
```

`judge.stamp()` blanks `judge_location` at tier 0, reasonably, because no judge ran. But the
declaration is **not a property of the judge** — it is the user's correction to the host, and
embeddings go to that same host at both tiers. So the correction lived only in the field that
is erased half the time, and a tier-0 verdict from a tunnelled host read back as *never left
the machine* while every embedding went through the tunnel.

The fix that was supposed to close the hole closed it at tier 1 and left it open at tier 0.
No red test would have found that: the tests I had written all set a judge model.

So the stamp records the ANSWER — `stayed_on_this_machine`, the address AND the user's
correction, at both tiers — and `judge_location` stays what it is, the tier-1 declaration.

### Row 121 survived first, because I had widened the window myself

Deleting the field from the README's enumeration left the suite green. The check takes a
window after the marker and looks for each phrase anywhere in it — and **I had widened that
window from 400 to 900 characters an hour earlier**, to fit a longer paragraph. The paragraph
explaining the field then stood in for the list that is supposed to name it.

Its own docstring says what it is for: *"it named five of seven ... which is how a guarantee
quietly stops covering the field nobody listed."* Cut to the first sentence now, which is the
enumeration and nothing else.

## Round twenty-one — is a package install a thing this project does?

`[tool.setuptools.packages.find] include = ["winnow*"]` leaves `packs/` out of the wheel, so
`pip install winnow` installs a tool with no domain packs. The README said "distributed by
clone, not as a package" in one place and CI built a wheel and ran `twine check` on it in
another, with nothing anywhere stating whether a package release was intended. A reader could
reasonably have concluded the missing packs were an oversight.

Operator decision, 2026-09-09: **PyPI is out of scope.** Recorded in the README rather than
in a conversation, and tied to the packaging by a test that fails in either direction — put
the packs into the wheel one day and it asks for the statement to be rewritten.

| # | mutation applied | test | result |
|---|---|---|---|
| 122 | the scope decision not stated | `test_the_packaging_and_the_statement_agree` | RED |
| 123 | the ruling given with no reason | `test_the_reason_is_given_not_just_the_ruling` | RED |
| 124 | the wheel including the packs after all | `test_the_packaging_and_the_statement_agree` | RED |
| 125 | CI installing without `-e` | `test_ci_still_builds_because_the_documented_install_depends_on_it` | RED |
| 126 | the stated round count disagreeing with the headings | `test_the_stated_round_count_matches_the_headings` | RED |
| 127 | the stated behaviour count disagreeing with the rows | `test_the_stated_behaviour_count_matches_the_tables` | RED |
| 128 | the count check reading a quoted old claim | `test_the_stated_round_count_matches_the_headings` | RED |

### The walk was the only thing that could check this one

There is no code in this round: the change is a paragraph and a test. So the walk was to run
the claim. Built the wheel, installed it into a clean virtual environment, and ran it from a
directory with no repository in sight:

```
entries: 21   anything under packs/: none
pip install: exit 0
winnow packs    exit 1    no packs found.
```

Exit 1 confirmed. **And the quoted message was wrong** — I had written that it exits with
"no domain packs found", which is the wording of the exit-code TABLE, not of the message. The
tool says `no packs found.` I quoted a string I had not read, into the paragraph explaining
why a whole distribution channel is closed.

Row 123 also survived its first mutation, for the familiar reason: replacing one clause left
"packs" and "pip install -e ." standing elsewhere in the same paragraph, so the section went
on giving the reason. A mutation has to remove the behaviour, not a sentence of it.

### This document's own checker agreed with a mistake it was recording

Writing "twenty-one" turned the suite red, and the message was:

```
the summary says five (5) rounds; there are 21 headings
```

There is no "five" in the summary. The pattern was `behaviours, over ([a-z]+) rounds`, and
`[a-z]+` cannot match a hyphen, so the search slid down the document and matched the
parenthetical near the top that **quotes the old wrong line** — *"26 behaviours, over five
rounds"* — the very error this file records having made.

The hyphen is a spelling bug and would have bitten at round twenty-one whatever else was
true. The unanchored search is the real one: **a file whose subject is claims that turned out
to be wrong will always contain quoted wrong claims**, so a loose search over it is
guaranteed to find one eventually and cannot tell it from the current claim. Anchored on the
bold summary line now — which is the anchoring its sibling `\*\*(\d+) behaviours` already
had, and why that one never hit this.

## Round twenty-two — the diagnostic wrote to whatever it was pointed at

`winnow status` was fixed once already: it no longer creates a corpus that is not there. But
when the file exists it still built a `Store`, and the constructor runs `executescript(SCHEMA)`
and commits. Measured — size, sha256 and table list, before and after one `winnow status`:

```
zero-byte file        0 B, no tables    ->  53,248 B, 4 tables
older schema     12,288 B, ['claims']   ->  36,864 B, 4 tables, THEN exit 5
a budget          8,192 B, ['budget']   ->  57,344 B, ['budget','claims','meta',
                                                       'sources','verdicts']
```

The third case is the one that matters: mistype `corpus_path` onto a SQLite file belonging to
something else, and the diagnostic adds four tables to it and exits 0 without a word. The
second modified the file on its way to reporting the corpus unreadable.

"Remember to open it read-only" is not a mechanism. SQLite has one: `mode=ro` makes the
database refuse the write, so a query added later that turns out to write fails loudly
instead of quietly changing someone's file.

| # | mutation applied | test | result |
|---|---|---|---|
| 129 | `status` back to the writing constructor | `test_status_does_not_touch_someone_elses_database` | RED (3) |
| 130 | `mode=rw` instead of `mode=ro` | `test_a_read_only_store_refuses_writes` | RED |
| 131 | the URI built by concatenation | `test_a_corpus_path_is_a_filename_not_a_uri` | RED |
| 132 | the read-only connection without `row_factory` | `test_status_still_reports_a_real_corpus` | RED (8) |

### Row 131 is a bug the walk found in the fix, twenty minutes old

`open_readonly` used `cls.__new__(cls)`, so the walk went looking for the classic failure —
an attribute `__init__` sets that the new door forgets. `vars()` matched on both; that was not
it. What the walk did find was the URI:

```
with#hash    OperationalError: no such table: claims
```

A corpus inside a directory called `with#hash`, opened by name, is **not the corpus that is
opened.** `f"file:{path}?mode=ro"` builds a URI by concatenation, and a filename is not URI
text: `#` starts a fragment, so the name is truncated and SQLite is handed a different file.
Winnow then reports a corpus sitting right there as not being one.

The `?` case is worse and is legal on Linux and macOS: it starts the query string, so a
directory name could supply the parameters and drop the `mode=ro` that is the entire purpose
of the constructor. `Path.resolve().as_uri()` percent-encodes both (`%23`, `%3F`).

Green at 675 tests when the walk started. No test had an awkward character in a path, and
none would have: the fixtures all use `tmp_path`, which is tidy by construction.

## Round twenty-three — one question, two implementations, two answers

The pipeline refuses a corpus whose stored embedding model is not the one in use, comparing
against `embedder.name`. `status` did the same check by hand, comparing against
`config.embed_model`. Those strings are equal for the Ollama backend and not for the hashing
one:

```
backend=hashing   config.embed_model='nomic-embed-text'   embedder.name='hashing-256'
```

So on a corpus built with `embed_backend: "hashing"`, read back with **exactly the settings
that built it**, `winnow status` printed `UNUSABLE -- these claims were embedded with
'hashing-256', not 'nomic-embed-text'` and exited 6 — while `index` and `ingest` on the same
corpus ran without complaint, because they ask the embedder rather than the file.

The review reported it as a comparison mismatch. The false `UNUSABLE` is what it causes, and
it is the same shape as round twenty: the command whose job is to tell you whether something
is wrong, telling you something alarming that is not true.

| # | mutation applied | test | result |
|---|---|---|---|
| 133 | `status` comparing against the file's model name again | `test_status_does_not_cry_mismatch_over_a_corpus_it_just_built` | RED (2) |
| 134 | the model in use not excluded from the foreign list | `test_the_comparison_is_one_function` | RED (19) |
| 135 | the pipeline no longer refusing a foreign corpus | `test_the_pipeline_still_refuses_a_foreign_corpus` | RED (3) |
| 136 | `status` no longer reporting a real mismatch | `test_status_still_reports_a_real_mismatch` | RED (4) |

The comparison is now one function, `foreign_embed_models`, called by both. Two copies is not
a duplication problem to tidy up later — it is how the two answers came to differ at all.

### What the walk checked that the tests do not

`status` now calls `build_embedder`, which is new work inside a command whose whole
contract is that it does none. Walked with `socket.socket` replaced by a tripwire:

```
build_embedder('hashing') -> name='hashing-256'       no socket opened
build_embedder('ollama')  -> name='nomic-embed-text'  no socket opened
```

The Ollama embedder constructs a client and does not connect until it is asked to embed, so
the diagnostic still touches no network. And running the old comparison beside the new one
over every corpus/backend pair showed them differing in exactly the two hashing cases and
agreeing in the other four — which is why this survived every test the repository had.

## Round twenty-four — a whole corpus of noise could be built in silence

`embed_backend: "hashing"` hashes the text instead of understanding it: two claims that say
the same thing in different words score no closer than two unrelated ones. Every similarity
it produces is noise, and only `ingest` said so — after the fact, attached to the verdicts.
Measured on the others:

```
status   exit 0   "embeddings    : nomic-embed-text via hashing"   (a config line)
index    exit 0   no mention of hashing at all
rejudge  exit 0   no mention of hashing at all
```

So a corpus could be built entirely with it and re-judged with it without a word, and
`status` — the command someone runs when results look wrong — printed it beside the model
name as an ordinary setting rather than the answer.

| # | mutation applied | test | result |
|---|---|---|---|
| 137 | the choke point not warning | `test_index_says_so_before_building_a_corpus_of_noise` | RED (2) |
| 138 | `status` not warning | `test_status_calls_the_test_backend_what_it_is` | RED |
| 139 | the warning firing for the wrong backend | `test_a_real_backend_is_not_warned_about` | RED (4) |
| 140 | the warning firing for every backend | `test_a_real_backend_is_not_warned_about` | RED |

Printed from `Pipeline.build`, the same choke point `announce_destination` uses, for the same
reason: a warning each command has to remember to print is one the next command will not.
`status` builds no pipeline, so it says it itself.

### What the walk settled

Every command, both backends, both streams:

```
              hashing              ollama
status        stdout               silent
packs         NOWHERE              silent
index         stderr               -
rejudge       stderr               -
ingest        stderr               -
```

`packs` not warning is correct and worth having checked rather than assumed: it builds no
pipeline, reads no corpus and issues no verdict, so there is nothing to mistrust.

The stream split is also deliberate and now verified rather than intended: `status` writes
its report to stdout so the warning belongs there, while `Pipeline.build` writes to stderr
beside the destination line, so a script parsing verdicts out of stdout is not disturbed.

`ingest` carries two messages now — one before the work and one attached to the results.
Counted: one each, not a doubled sentence.

## Round twenty-five — a proxy in the environment answered for Ollama

`urllib` reads `http_proxy` and does not bypass loopback on its own. Measured with a listener
standing in for a proxy and `ollama_host` at its default:

```
fake proxy received: POST http://localhost:11434/api/embeddings HTTP/1.1
embed() returned   : [0.1, 0.2]
```

Two failures at once. The text left the machine while `winnow status` printed *"never
transmitted"* — and the vector came back **from the proxy**, not from Ollama, so the result
was wrong as well as leaked, and nothing in Winnow could tell the difference. An environment
variable, set by an IT department years ago, silently becomes a recipient of every claim,
every note and every transcript.

A loopback address has no legitimate reason to be proxied, and an SSH tunnel binds a local
port directly, so refusing the proxy there does not break the forwarded-host case
`judge_location: "cloud"` exists for. A genuinely remote host still honours the environment —
a proxy is how many networks reach anything at all — and the privacy statement now names it,
because it is a third party receiving the material.

| # | mutation applied | test | result |
|---|---|---|---|
| 141 | the request going through urllib's default opener | `test_a_proxy_does_not_receive_a_request_meant_for_localhost` | RED |
| 142 | loopback no longer refusing the proxy | `test_a_proxy_does_not_receive_a_request_meant_for_localhost` | RED (2) |
| 143 | `bypasses_proxy` false for loopback | `test_every_spelling_of_loopback_is_covered` | RED (6) |
| 144 | `bypasses_proxy` true for a remote host | `test_a_remote_host_still_honours_the_proxy` | RED (2) |
| 145 | loopback matched by suffix rather than exactly | `test_a_name_that_merely_resembles_loopback_is_not_loopback` | RED (2) |
| 146 | the proxy unnamed in the privacy statement | `test_the_privacy_statement_names_the_proxy_for_a_remote_host` | RED |
| 147 | `host_is_local` true for a remote host | across the suite | RED (15) |

### Row 145 survived first, and the lookalike I chose was the wrong shape

`host in LOOPBACK_HOSTNAMES` mutated to `host.endswith(LOOPBACK_HOSTNAMES)` left the suite
green. The only lookalike hostname anywhere in the tests was `localhost.evil.example` — a
**prefix**. It does not end in "localhost", so a suffix rule classifies it correctly and the
mutation changed nothing observable.

`not-localhost` and `evil.localhost` are the shapes that separate the two rules, and neither
is verifiably this machine. A check that decides whether text leaves the machine fails closed
on anything it cannot be certain of.

### What the walk added

The probe that found the defect used a fake proxy and watched the request arrive; the walk
repeated it against the fixed code, because **a property returning True is not evidence that
a packet did not go somewhere**:

```
loopback   bypasses_proxy=True    proxy received 0 new requests
remote     bypasses_proxy=False   proxy received 1: POST http://box.example:11434/...
```

It also recorded a deliberate imprecision. `_proxy_for` falls back to the HTTP proxy when the
scheme has none of its own, so for an `https` host with only `http_proxy` set it can name a
proxy urllib would not actually use. That **over**-discloses, which is the safe direction for
a privacy statement, and it is written down rather than left to be rediscovered.

The loopback test now lives in one function shared by the privacy statement and the HTTP
client. Two implementations of "is this local" is how two answers start to disagree — the
same fault as round twenty-three, avoided rather than repeated.

## Round twenty-six — a command that was cheap at one tier and unmeasured at the other

`index` measures one file, projects the run, shows the number and refuses until a budget
covers it. `rejudge` walked every claim and called `judge_claim` on each. At tier 0 that is
embeddings only and genuinely cheap — which is what the docstring said:

> "Re-judging is cheap with embeddings, so a stale verdict is a choice rather than a
> constraint."

Set `judge_model` and every claim becomes a model call. On the 383-claim corpus this was
developed against, 383 of them, with no projection and no gate. **The docstring was half the
defect**: it described tier 0 and was read as describing the command.

| # | mutation applied | test | result |
|---|---|---|---|
| 148 | a tier-1 rejudge not measured before it runs | `test_a_tier_one_rejudge_is_projected` | RED (2) |
| 149 | the verdict stored before the gate | `test_a_refused_rejudge_changes_nothing` | RED |
| 150 | the measured claim judged a second time | `test_the_measured_claim_is_judged_once` | RED |
| 151 | tier 0 gated as well | `test_a_tier_zero_rejudge_is_not_gated` | RED |
| 152 | the budget dropped between the flag and the gate | `test_the_budget_on_the_command_line_reaches_the_gate` | RED |
| 153 | the flag renamed away from what the message says | `test_the_cli_offers_the_budget_flag` | RED |

### Rows 149 and 152 survived the first battery

Both are guarantees I believed, had checked by hand in the walk, and had not written down.

**149.** Moving `add_verdict(first)` to before the gate left the suite green. The
corpus-is-untouched rule was established for `index` in an earlier round and recorded there;
nothing held it for this command, so the ordering was free to be reversed by anyone.

**152.** `pipeline.rejudge()` with the budget dropped left the suite green: the flag was
parsed and nothing proved it reached the gate. The refusal message tells the user to re-run
with `--accept-minutes N` — a flag the command accepts and ignores sends them in a circle,
and is worse than no flag at all.

The walk had verified both. **A walk is evidence about the code as it stands; a test is
evidence about the code as it will stand.** Neither replaces the other.

### What the walk established

```
judge.tier = 1
verdicts 33, model calls 33, claims 33   -> one call per claim
projection: unit=0.0215s x 33 = 0.709s   (reality: 33 x 0.02 = 0.66s)

refused run:  corpus digest 4f4a2ff16a23700b -> 4f4a2ff16a23700b  UNCHANGED
              counts (33, 33) -> (33, 33)
              model calls spent measuring: 1
tier 0:       projection=None  verdicts=33
empty corpus: verdicts=0  projection=None  model calls=0
```

And one honest limitation, recorded rather than smoothed over: the sample is `rows[0]`, which
is whatever order SQLite returns, not a median as `index` uses. Measured claim lengths in that
corpus span **28 to 86 characters, a 3.1x spread**, against the 18x spread across files that
made median sampling necessary there — and a judge call's cost is dominated by the prompt
template and the neighbour claims rather than by the claim itself. Unit times count is the
honest estimator here; if that stops being true, this paragraph is where to look.

## Round twenty-seven — a fetch that could hang forever, invisibly

`subprocess.run(command, capture_output=True, text=True)`. No timeout, so a stalled
connection or a site that accepts and never answers left Winnow waiting with the
`running: yt-dlp ...` line on screen and nothing after it, with no end. Ctrl-C was the only
exit and it killed the run rather than the fetch.

`capture_output=True` is the second half, and it is right for captions — seconds of work,
and the text is what the failure message quotes. For `--with-video` it is wrong: hundreds of
megabytes with yt-dlp's own progress display swallowed until the process ends, so a download
that is working looks exactly like one that has hung.

| # | mutation applied | test | result |
|---|---|---|---|
| 154 | a caption fetch unbounded again | `test_a_hung_fetch_is_stopped_rather_than_waited_on` | RED (2) |
| 155 | a video download captured again | `test_a_video_download_is_watched_rather_than_captured` | RED |
| 156 | the timeout message not naming the setting | `test_a_hung_fetch_is_stopped_rather_than_waited_on` | RED |
| 157 | an uncaptured failure quoting nothing | `test_a_failed_video_download_still_says_where_to_look` | RED |
| 158 | the configured timeout dropped in `cmd_ingest` | `test_the_command_line_passes_the_configured_timeout` | RED |
| 159 | the field default a copy of the constant | `test_the_field_default_is_the_constant_not_a_copy_of_it` | RED |

### The walk, against real subprocesses

Fakes prove the arguments are passed. Only a real process proves the timeout fires:

```
a stand-in that sleeps 60s, limit 2s   -> raised after 2.02s
a second bounded call                  -> returned in 1.02s (nothing left running)

captions    yt-dlp's line reached the terminal: False   winnow quoted: ERROR: something went wrong
with_video  yt-dlp's line reached the terminal: True    winnow quoted: (yt-dlp's output is above)
```

### Row 159: the walk found a defect it had just watched me commit

Two constants held 600 — `Config.fetch_timeout_seconds` and `acquire.DEFAULT_FETCH_TIMEOUT` —
agreeing by coincidence with nothing to keep them agreeing. **That is the same shape as round
twenty-three**, where `status` and the pipeline compared different model names that happened
to be equal for one backend, and I introduced it in this fix about an hour after writing that
round up. One definition now: the constant lives in `config`, `acquire` imports it, and the
dataclass default IS it.

### Three survivors, and what each says about the test rather than the code

**157.** Deleting the "(yt-dlp's output is above)" fallback left the suite green: my assertion
was `"above" in said`, and the standing advice block already contains *"yt-dlp's own message
is above and is the thing to read"*. The test passed on the wrong sentence. It now asserts
the SHAPE — the line under the exit-code line must not be blank.

**158.** Dropping `timeout_seconds=` from `cmd_ingest` left the suite green: nothing covered
the wiring. This is the identical gap to the rejudge budget one round earlier, and I did not
generalise the lesson when I had it. **An argument that is parsed, accepted and dropped needs
its own test, every time.**

**159.** Replacing the constant with a literal `600` left the suite green *correctly*. The
behaviour is "the two agree", and a literal 600 agrees; what the mutation removes is the
MECHANISM that keeps them agreeing. No value comparison can see that, so the check reads the
source — the same instrument the documented-defaults tests use.

## Round twenty-eight — the third fix to one discriminator, and the first that is not a list

`winnow ingest data.backup` answered *"looks like a link with no scheme. Try
https://data.backup"*. So did `report.docx`, `archive.zip` and `notes.tar.gz`.

This is the **third** time this one predicate has been fixed:

1. The original guard was written against `notes/talk.txt`, which has a separator — so a
   bare `README.md` still matched and an existing file was told to try `https://README.md`.
   That round's own note says it "tested the shape I had in mind rather than the class".
2. The fix was a list of the extensions Winnow READS. `.backup`, `.docx` and `.zip` are not
   on it and never will be, because the list is of things the tool can open.
3. **The class is "a filename", and no list of extensions describes it.**

`.zip` is a real top-level domain. No rule separates `archive.zip` the file from
`archive.zip` the host, and every attempt to write one has been an attempt to resolve
something genuinely undecidable. So the answer is undecided too: a bare dotted name is
reported as a missing FILE — the likelier reading — with the link reading offered on the next
line. What is not ambiguous is a host followed by a PATH, which is what a pasted YouTube link
always looks like, and that keeps the confident advice.

| # | mutation applied | test | result |
|---|---|---|---|
| 160 | the host pattern's path made optional again | `test_a_bare_dotted_name_is_not_declared_a_link` | RED (13) |
| 161 | a readable filename no longer spared the hint | `test_a_mistyped_filename_reports_a_missing_file` | RED (4) |
| 162 | the message quoting the normalised path | `test_the_message_quotes_what_was_typed` | RED |
| 163 | the other reading not offered | `test_the_command_reports_a_missing_file_and_offers_the_other_reading` | RED (4) |

### A census, because two example-shaped fixes had already failed here

The walk did not test a few strings. It ran every KIND of input through the predicate and
printed what a user would see — the thing that was wrong both previous times:

```
a link pasted without its scheme    youtu.be/IGBp6QdsR2s     LINK ADVICE
a bare host, no path                youtube.com              -
a filename Winnow reads             talk.txt                 -          file
a filename Winnow does not read     data.backup              -
a relative path                     notes/talk.txt           -          file
a broken scheme                     ftp://example.com/x      LINK ADVICE
```

### Row 162 is a defect the walk found in a message it was only passing through

```
$ winnow ingest notes/talk.txt
no such file or folder: notes\talk.txt
```

`Path()` normalises the separators, so the string quoted back is not the one on the user's
command line. **`why_not_a_url`'s own docstring names this as part of why that function
exists** — *"with the separators flipped by `Path()`, so the string quoted back was not even
the one the user typed"* — and the failure branch one line below it was still doing it. The
fix for a problem, sitting directly above an unfixed instance of the same problem.

### The suffix list kept its place, in a different role

It no longer answers "is this a host?" — the host pattern settles that by requiring a path.
It answers "is this so obviously a file that mentioning the link reading would be noise?"
`talk.txt` gets no hint, which is what an earlier round decided and its test still asserts.

## Round twenty-nine — Ctrl-C, and a check that read a comment as a socket

`index` on a real notes folder is minutes to hours, and Ctrl-C is the documented way to
change your mind about it — the projection is shown before the work starts and there is no
other exit. What it printed was a `KeyboardInterrupt` stack trace through `pipeline.py`,
`extract.py` and `llm.py`, ending in a sleep or a socket read. That reads as a crash, and it
buries the question the user actually has: **is the work I have already paid for still
there?**

It is: `index_notes_folder` commits per file and `skip_known` filters out what is stored, so
an interrupted index resumes. Nothing said so, and a stack trace is not where anyone looks
for reassurance. Exit 130 now — 128 + SIGINT — with the message, and the code in the table.

| # | mutation applied | test | result |
|---|---|---|---|
| 164 | the interrupt escaping again | `test_an_interrupt_is_not_a_traceback` | RED (38) |
| 165 | a different exit code for an interrupt | `test_an_interrupt_is_not_a_traceback` | RED (2) |
| 166 | the message announcing the stop and nothing else | `test_it_says_the_work_so_far_is_kept` | RED |
| 167 | the README documenting a code the tool does not return | `test_the_exit_code_is_documented` | RED (2) |
| 168 | comments no longer excluded from the outbound scan | `test_the_scanner_reads_code_and_not_comments` | RED (2) |
| 169 | the scanner discarding the code it does not strip | `test_the_scanner_reads_code_and_not_comments` | RED (2) |

Row 164's blast radius is the finding in itself: an escaping `KeyboardInterrupt` does not fail
a test, it **aborts pytest**. The suite did not report a failure; it stopped.

### Rows 168 and 169: the sixth time a check has matched my own prose

The fix above added a comment saying the old traceback ended "in a sleep or a **socket**
read". `test_the_list_of_outbound_paths_is_complete` then refused `winnow/cli.py` as a file
that might reach the network. It cannot; the word is in a comment about a defect.

That is the sixth occurrence in this repository and the **second today** — the markdown link
checks did it this morning and were fixed by scanning prose with the code removed. This is
the mirror: scan code with the prose removed, using `tokenize`, which knows where a string
ends rather than guessing.

**And the first version of that fix was worse than the bug.** Joining the surviving tokens
with spaces turned `subprocess.run` into `subprocess . run`, so the pattern matched nothing:
the check would have found no outbound file in any repository and passed everywhere. The
guard test written beside it said so on the first run — *"real code was stripped away"* —
before the change was committed. The spans are blanked in place now, so every other character
keeps its column.

### Row 166 survived first, on an `or`

The assertion was `"kept" in said or "already" in said`. Deleting the sentence that says the
work survives left the suite green, because the sentence AFTER it happens to contain
"already". A user has two questions — did I lose the work, and how do I carry on — and the
message owes both answers, so the test now requires both.

The first replacement mutation was also ill-formed: it cut one source line out of a string
that spans four, and "picks up where it" survived in the fragment above. Replacing the whole
message with its headline is the mutation that removes the behaviour.

## Round thirty — the destination arrived, and the guard waiting for it had never worked

Review item 14 was the one finding that could not be fixed from inside the repository: the
README said `git clone https://github.com/<you>/winnow.git` and the review's instruction was
not to invent a destination. It was recorded as a **strict xfail** so that the day a real URL
replaced the placeholder, the test would pass, `strict=True` would turn passing into a
failure, and the marker would come off. A blocker held in the suite rather than in a note.

The URL arrived. The xfail did not move.

```
matches: ['<url>', 'Your ', 'your ']
```

The check applied the metadata placeholder pattern to the README. `<url>` is the usage line
`winnow ingest <url|path>`. **`Your ` and `your ` are English** — `\bYOUR[_ ]` under
`re.IGNORECASE`, against a document written in the second person. The test could not pass
however many placeholders were fixed, so the mechanism built to notice the answer arriving
was inert from the moment it was written.

**A test that cannot succeed, standing guard over the one finding that needed a human.** Had
the URL been supplied and the xfail consulted, the honest reading would have been "still
blocked" — for ever.

| # | mutation applied | test | result |
|---|---|---|---|
| 170 | a clone URL with the placeholder back in it | `test_every_clone_url_in_the_readme_is_real` | RED (2) |
| 171 | one metadata URL pointing at another repository | `test_the_readme_and_the_metadata_name_the_same_repository` | RED |
| 172 | the package not saying who wrote it | `test_the_package_says_who_wrote_it` | RED |
| 173 | `[project.urls]` removed | `test_the_readme_and_the_metadata_name_the_same_repository` | RED |
| 174 | the placeholder pattern matching prose again | `test_the_placeholder_pattern_does_not_fire_on_ordinary_english` | RED |
| 175 | the placeholder pattern matching nothing at all | `test_the_placeholder_pattern_still_finds_real_placeholders` | RED |

### Row 171 survived first, on "somewhere" rather than "everywhere"

Pointing `Homepage` at a different repository left the suite green, because the test asked
whether the clone URL appeared among the metadata URLs and `Source` and `Issues` still held
it. One wrong link among three is precisely the case worth catching: a Homepage nobody clicks
is where a stale address survives. Every GitHub URL is checked now, not one of them.

### Row 174 is the defect above, written down as a test

Restoring `re.IGNORECASE` was harmless *today* — the pattern is no longer applied to prose,
so nothing failed. That is not a reason to leave it unrecorded: it is the exact fault that
made a guard unable to fire, and the only thing standing between it and a repeat was my
memory of an afternoon. Now the pattern is asserted, in both directions, against a paragraph
of ordinary second-person English and against six real placeholders.

### What the walk checked that no test does

The tests read `README.md` and `pyproject.toml`. Neither is what a user receives, and a URL
in a package is a promise that something is at the other end. So: build the wheel, read its
METADATA, and resolve every published address against GitHub.

```
Author-email: bkoken20 <57477482+bkoken20@users.noreply.github.com>
Project-URL: Homepage, https://github.com/bkoken20/winnow
Project-URL: Source,   https://github.com/bkoken20/winnow
Project-URL: Issues,   https://github.com/bkoken20/winnow/issues

https://github.com/bkoken20/winnow        -> bkoken20/winnow, public=True
https://github.com/bkoken20/winnow.git    -> bkoken20/winnow, public=True
https://github.com/bkoken20/winnow/issues -> bkoken20/winnow, public=True
```

And one hazard recorded rather than fixed: the `Issues` URL is checked for naming the right
repository, not for issues being enabled. If they are ever turned off that link 404s and no
test here would notice. `has_issues` was true when the repository was checked.
