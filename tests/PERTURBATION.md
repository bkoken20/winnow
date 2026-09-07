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

### Two mutations that came back GREEN, and what each meant

Both were faults in the *mutation*, not gaps in the tests — worth recording, because a
perturbation that fails to break the code proves nothing either way and it is tempting to
read it as a passing grade.

- Replacing `docs/PARAMETERS.md` in the README hit the link's display text, leaving the href
  valid. Mutating the href turned it red.
- Disabling the scheme check alone left a second layer intact (`""` no longer counts as
  loopback). Restoring both halves of the original defect turned it red.
