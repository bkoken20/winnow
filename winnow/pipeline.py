"""Wiring: notes and media in, claims and verdicts out."""

from __future__ import annotations

import hashlib
import sys
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

from .config import Config
from .cost import Projection, accepted_by_flag, gate, time_one
from .embed import build_embedder, cosine_similarity
from .extract import Extractor
from .judge import Judge, JudgeConfig
from .llm import OllamaClient, OllamaError
from .media import (
    TEXT_EXTENSIONS,
    FFmpegMissing,
    extract_frames,
    find_media_file,
    transcript_for,
)
from .models import NOVELTY_KNOWN, Claim, Source, Verdict
from .packs import Pack, find_pack
from .store import Store

NOTE_EXTENSIONS = TEXT_EXTENSIONS


class CorpusEmbeddingMismatch(RuntimeError):
    """The corpus was built with a different embedding model than the one configured.

    Refused rather than warned. Vectors from two models are not comparable and mismatched
    dimensions are skipped entirely during search, so the corpus becomes invisible: every
    claim comes back `new` against a corpus that may hold ten thousand of them. Confident
    wrong answers are worse than a stop.
    """


def announce_destination(config: Config, *, stream=None) -> None:
    """Say where the data is going, before any of it goes.

    The README promises Winnow states what leaves your machine. `egress_statement()` delivers
    that and was printed by exactly ONE command -- `status` -- while `index`, `ingest` and
    `rejudge`, the three that actually transmit transcripts, notes and claims, said nothing.
    Set `ollama_host` to another machine and every word of your material went there
    undisclosed.

    It lives here, in the constructor every processing path passes through, rather than in
    each command: one command remembering and the next forgetting is precisely how this
    happened, and a rule enforced by memory is not enforced.

    stderr, and flushed, for the same reason the fetch command is -- a disclosure that
    arrives after the thing it describes is not a disclosure. Progress belongs off stdout so
    a caller parsing output does not have to filter it.
    """
    print(f"destination: {config.egress_statement()}",
          file=stream or sys.stderr, flush=True)


def source_id_for(path: Path) -> str:
    return hashlib.blake2b(str(path.resolve()).encode("utf-8"), digest_size=10).hexdigest()


@dataclass
class Pipeline:
    config: Config
    store: Store
    pack: Pack
    extractor: Extractor
    judge: Judge
    llm: OllamaClient

    @classmethod
    def build(cls, config: Config) -> "Pipeline":
        packs_root = Path(config.packs_root) if config.packs_root else None
        pack = find_pack(config.pack, packs_root)
        store = Store(config.corpus_path)
        embedder = build_embedder(
            config.embed_backend, config.embed_model, config.ollama_host
        )
        llm = OllamaClient(host=config.ollama_host)
        # The extractor is built for indexing; `ingest` swaps in its own pass list, which
        # is more thorough because judging one item costs seconds while indexing a whole
        # corpus costs hours.
        extractor = Extractor(
            llm=llm,
            model=config.text_model,
            num_ctx=config.text_num_ctx,
            pack=pack,
            chunk_chars=config.chunk_chars,
            extra_passes=tuple(config.index_extra_passes),
        )
        judge = Judge(
            store=store,
            embedder=embedder,
            config=JudgeConfig(
                pack=pack.name,
                pack_version=pack.version,
                min_corpus=pack.min_corpus,
                judge_model=config.judge_model,
                judge_location=config.judge_location,
                judge_num_ctx=config.judge_num_ctx,
            ),
            llm=llm if config.judge_model else None,
        )
        pipeline = cls(config, store, pack, extractor, judge, llm)
        pipeline.check_corpus_embeddings()
        announce_destination(config)
        return pipeline

    def check_corpus_embeddings(self) -> None:
        """Refuse to run against a corpus embedded by a different model."""
        in_use = self.store.embed_models_in_use(self.pack.name)
        current = self.judge.embedder.name
        foreign = sorted(in_use - {current})
        if not foreign:
            return
        raise CorpusEmbeddingMismatch(
            f"corpus '{self.config.corpus_path}' holds claims embedded with "
            f"{', '.join(repr(m) for m in foreign)}, but embed_model is {current!r}.\n"
            "  Vectors from different models cannot be compared, so the existing corpus "
            "would be invisible and every claim would look new.\n"
            f"  Either set embed_model back to {foreign[0]!r}, or start a fresh corpus "
            "(change corpus_path, or delete the file) and re-index."
        )

    # -- corpus building -------------------------------------------------------

    def is_near_duplicate(self, vector: list[float]) -> bool:
        """Is this claim already in the corpus in different words?

        Exact-hash de-duplication is not enough once more than one extraction pass runs
        over the same text: the passes cut the text at different points and produce genuine
        rewordings of the same assertion (~19% of the merged set, measured). Storing those
        inflates the corpus and, worse, makes later novelty verdicts read `known` because
        the corpus is echoing itself.
        """
        threshold = self.config.duplicate_threshold
        if threshold <= 0:
            return False
        nearest = self.store.similarity_search(self.pack.name, vector, top_k=1)
        return bool(nearest) and nearest[0].similarity >= threshold

    def _duplicates_within_batch(
        self, vector: list[float], already_stored: list[list[float]]
    ) -> bool:
        """Is this claim a reworded copy of one stored earlier in the SAME batch?

        `is_near_duplicate` asks the database, which during ingest has not yet received the
        current batch. Without this, three passes over one text store three wordings of the
        same assertion because none of them was in the corpus when the batch began.
        """
        threshold = self.config.duplicate_threshold
        if threshold <= 0:
            return False
        return any(cosine_similarity(vector, v) >= threshold for v in already_stored)

    def index_note(self, path: Path) -> int:
        """Extract claims from one note and add them to the corpus. Returns claim count."""
        text = path.read_text(encoding="utf-8", errors="replace")
        sid = source_id_for(path)
        # Extract FIRST. Recording the source before extraction meant a run that died --
        # most often because a model was never pulled -- still committed the source row, and
        # `skip_known` then filtered that path out for ever. Fix the model, run again, and
        # Winnow reported "nothing new to index" and exited 0. A source is recorded when it
        # has been processed, not when processing was attempted.
        claims = self.extractor.extract(text, sid)

        # EVERY fallible step before the first commit. `add_source` and `add_claim` each
        # commit on their own, so there is no transaction to roll back: the only way to make
        # a source's completion atomic is to finish the work that can fail first.
        #
        # Moving `add_source` after extraction was not enough -- embedding runs after it, so
        # the same failure one step later had the same consequence: the source recorded, the
        # claims missing, and `skip_known` filtering the file out of every future run. It is
        # the same scenario as well, since "the model was never pulled" applies to the
        # embedding model exactly as it does to the extraction model.
        vectors = [self.judge.embedder.embed(claim.text) for claim in claims]

        self.store.add_source(
            Source(id=sid, pack=self.pack.name, kind="note", path=str(path), title=path.stem)
        )
        stored = 0
        for claim, vector in zip(claims, vectors):
            if self.is_near_duplicate(vector):
                continue
            self.store.add_claim(claim, vector, self.judge.embedder.name)
            stored += 1
        return stored

    def index_notes_folder(
        self, folder: Path, accept_minutes: float | None = None, skip_known: bool = True
    ) -> dict:
        """Index a folder of notes, measuring one before committing to all of them."""
        folder = Path(folder)
        if not folder.is_dir():
            raise NotADirectoryError(f"{folder} is not a directory")

        files = sorted(
            p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in NOTE_EXTENSIONS
        )
        if skip_known:
            known = self.store.source_paths(self.pack.name)
            files = [p for p in files if str(p) not in known]
        if not files:
            return {"files": 0, "claims": 0, "projection": None}

        # Measure one real unit, then project by TEXT VOLUME rather than by file count.
        # File sizes in a real notes folder vary by more than an order of magnitude, so
        # "time one file, multiply by the number of files" is only a valid estimator when
        # the sampled file happens to be typical. Sample a median-sized file and scale on
        # bytes instead.
        total_bytes = sum(p.stat().st_size for p in files)
        by_size = sorted(files, key=lambda p: p.stat().st_size)
        sample = by_size[len(by_size) // 2]

        corpus_before = self.store.count_claims(self.pack.name)

        # Scan cost is measured BEFORE the sample is indexed, so it describes the corpus the
        # sample will actually be compared against.
        scan_cost = self.store.measure_scan_cost(
            self.pack.name, self.judge.embedder.embed("cost probe")
        )

        first_claims, unit_seconds = time_one(self.index_note, sample)
        claims_per_file = max(int(first_claims), 1)

        # The measured unit time ALREADY contains the sample's own de-duplication scanning,
        # so projecting dedupe on top of it counts the same work twice -- which over-stated
        # a real 56-second run as 125 seconds. Subtract what the sample itself spent
        # scanning to recover the extraction-only cost, then project scanning separately
        # across the whole run.
        sample_scan_seconds = scan_cost * corpus_before * claims_per_file
        extraction_unit_seconds = max(unit_seconds - sample_scan_seconds, 1e-6)

        projection = Projection(
            unit_seconds=extraction_unit_seconds,
            measured_unit_seconds=unit_seconds,
            units=len(files),
            sample_bytes=sample.stat().st_size,
            total_bytes=total_bytes,
            scan_seconds_per_claim=scan_cost,
            corpus_claims_at_start=corpus_before,
            expected_new_claims=claims_per_file * len(files),
        )
        gate(projection, accepted_by_flag(accept_minutes, projection))
        files = [p for p in files if p != sample]

        total = int(first_claims)
        for path in files:
            total += self.index_note(path)
        return {"files": len(files) + 1, "claims": total, "projection": projection}

    # -- material intake -------------------------------------------------------

    def describe_frames(self, target: Path) -> str:
        """Sample frames from a media file beside the transcript and describe them.

        Returns an empty string whenever frames are unavailable for any reason -- no media,
        no ffmpeg, a vision model that will not answer. An ingest whose transcript is
        already in hand must not fail because the optional half is missing.

        Note there is no `as_json` here: `describe_image` cannot force JSON, because a
        description prompt asked for JSON produces garbled, invented output.
        """
        if not target.is_dir():
            return ""
        media = find_media_file(target)
        if media is None:
            return ""
        prompt = self.pack.render_frame_prompt()
        if not prompt:
            return ""

        # Frames go to a temporary directory, never into the user's folder. Winnow reads
        # what it is pointed at; writing JPEGs back into someone's source directory is a
        # side effect they did not ask for, fails outright on read-only or shared storage,
        # and leaves litter behind after an ingest.
        with tempfile.TemporaryDirectory(prefix="winnow-frames-") as tmp:
            try:
                frames = extract_frames(
                    media,
                    Path(tmp),
                    every_seconds=self.config.frame_every_seconds,
                    limit=self.config.max_frames,
                )
            except FFmpegMissing:
                return ""
            if not frames:
                return ""

            # Describing frames is the most expensive thing an ingest does -- one vision
            # call each, several seconds apiece -- and unlike indexing there is no cost
            # gate on this path. Say so before spending it, rather than appearing to hang.
            # Progress goes to stderr, not stdout: a caller importing this library may be
            # parsing what the tool prints, and describing frames is slow enough that
            # silence looks like a hang.
            print(
                f"describing {len(frames)} frames from {media.name} "
                f"({self.config.vision_model})...",
                file=sys.stderr,
                flush=True,
            )
            return self._describe_each(frames, prompt)

    def _describe_each(self, frames, prompt: str) -> str:
        described = []
        for frame in frames:
            try:
                text = self.llm.describe_image(
                    self.config.vision_model,
                    prompt,
                    frame.to_base64(),
                    num_ctx=self.config.vision_num_ctx,
                ).strip()
            except OllamaError:
                continue
            # The pack chooses its own "nothing here" token, so this cannot match a fixed
            # string. What it can check without being told is that the whole reply is upper
            # case -- which is therefore a REQUIREMENT on the token, and docs/DOMAIN_PACKS.md
            # says so: a lower-case sentinel is stored as a real description.
            if not text or text.strip("`\"' .").isupper():
                continue
            described.append(f"[{frame.seconds}s] {text}")
        return "\n".join(described)

    def _already_known(self, claim: Claim, vector: list[float]) -> Verdict | None:
        """A claim already stored is known by definition. `None` if it is not stored.

        Found by running the tool rather than reading it: a video already in the corpus,
        re-ingested, reported 60 of its 74 claims as NEW.

        The cause is a correct rule in the wrong place. `similarity_search` excludes the
        claim being judged, because a claim is not evidence about itself -- right, and
        necessary for `rejudge`. But re-ingesting produces the SAME claim ids (a hash of
        pack, source and text), so the second time round each claim's nearest neighbour is
        its own stored copy, and excluding it leaves only weaker matches. The tool then
        announces as a discovery something already in the corpus.

        The corpus IS what the reader already knows. If the claim is in it, the answer is
        known, and no similarity threshold should be consulted to decide otherwise.
        """
        if not self.store.claim_exists(claim.id):
            return None
        neighbours = self.store.similarity_search(
            self.pack.name, vector, top_k=self.judge.config.top_k,
            exclude_claim_id=claim.id,
        )
        return Verdict(
            claim_id=claim.id,
            novelty=NOVELTY_KNOWN,
            similarity=1.0,
            neighbours=neighbours,
            coverage=self.judge.coverage(claim.id),
            judge=self.judge.stamp(),
            rationale="this claim is already in your corpus -- the material has been ingested before",
        )

    def ingest(
        self, target: Path, judge_claims: bool = True
    ) -> tuple[list[Claim], list[Verdict]]:
        """Process one piece of material: transcript -> claims -> verdicts.

        `target` is a transcript file, a media file, or a folder already holding one. This
        method never fetches: `winnow ingest <url>` fetches first (see `winnow.acquire`)
        and then calls this with the folder it produced, so the two paths are identical
        from here on.
        """
        target = Path(target)
        text = transcript_for(target)
        if text is None:
            media = find_media_file(target) if target.is_dir() else None
            hint = (
                f"found media at {media.name} but no transcript beside it"
                if media
                else "no transcript or subtitle file found"
            )
            raise FileNotFoundError(
                f"{target}: {hint}. Winnow does not transcribe -- pass a video URL to "
                "fetch captions, or see docs/ACQUISITION.md for how to make a transcript "
                "yourself."
            )

        sid = source_id_for(target)

        # Judging one item is a matter of minutes, so it runs the thorough pass list even
        # when indexing does not: three passes take a 25-minute talk from 39% coverage to
        # 92% for about three extra minutes, while the same choice on a 7.5 MB corpus is
        # projected at 11.6 hours against 34.8 -- a projection, not a timed run
        # (experiments/TWO_PASS.md).
        extractor = replace(
            self.extractor,
            extra_passes=tuple(self.config.ingest_extra_passes),
        )
        # Frames, when the pack asks for them and the material actually has video. Their
        # descriptions are appended to the transcript so the extractor sees on-screen
        # content -- benchmark tables, terminal output, diagrams -- that the speaker never
        # reads aloud. Silent no-op when the pack does not use frames, when there is no
        # media file, or when ffmpeg is absent: none of those is a reason to fail an ingest
        # whose transcript is already in hand.
        if self.pack.use_frames:
            described = self.describe_frames(target)
            if described:
                text = f"{text}\n\n[ON-SCREEN CONTENT]\n{described}"

        claims = extractor.extract(text, sid)

        # PHASE 1 -- judge everything against the corpus AS IT WAS before this material.
        #
        # Judging and storing in one loop let a single transcript become its own evidence:
        # claim 26 of a 40-claim talk was judged against claims 1-25 of the same talk, which
        # both lifted a thin corpus over `min_corpus` and made a repeated point read `known`
        # because the speaker had said it a minute earlier. Nothing is written until every
        # verdict is decided.
        verdicts: list[Verdict] = []
        vectors = [self.judge.embedder.embed(c.text) for c in claims]

        # Recorded only now: extraction AND embedding have both succeeded, so this source
        # really was processed. Anything earlier marks a source complete while a step that
        # can still fail is outstanding -- see index_note above. Claims carry a foreign key
        # to it, so it must exist before anything is stored.
        self.store.add_source(
            Source(
                id=sid,
                pack=self.pack.name,
                kind="media",
                path=str(target),
                title=target.stem,
            )
        )

        if judge_claims:
            verdicts = [
                self._already_known(c, v) or self.judge.judge_claim(c, v)
                for c, v in zip(claims, vectors)
            ]

        # PHASE 2 -- store. Near-duplicate suppression belongs here as much as on the
        # indexing path, and more so: multi-pass extraction is the default for ingest and
        # reliably produces rewordings of one assertion. Suppression governs what is KEPT,
        # never what the reader is told -- every extracted claim keeps the verdict decided
        # above whether or not the corpus stores it.
        kept_vectors: list[list[float]] = []
        kept_claims, kept_verdicts = [], []
        verdict_by_claim = {v.claim_id: v for v in verdicts}
        for claim, vector in zip(claims, vectors):
            # Two passes over one text produce the same assertion twice. Reporting it twice
            # is noise -- worse, with the corpus frozen both copies now read `new`, so the
            # reader sees one discovery presented as two. Collapse within the batch.
            if self._duplicates_within_batch(vector, kept_vectors):
                continue
            kept_claims.append(claim)
            kept_vectors.append(vector)
            if claim.id in verdict_by_claim:
                kept_verdicts.append(verdict_by_claim[claim.id])

            # Claims already in the corpus keep their verdict -- `known` is informative and
            # must still be shown -- but are not stored again.
            if not self.is_near_duplicate(vector):
                self.store.add_claim(claim, vector, self.judge.embedder.name)
                if claim.id in verdict_by_claim:
                    self.store.add_verdict(verdict_by_claim[claim.id])

        claims, verdicts = kept_claims, kept_verdicts

        # The claims themselves are returned, not just a count, so a caller can report a
        # verdict without going back to the database for the text. That round trip is a
        # trap: callers close the pipeline in a `finally` and then format their output,
        # which reads from a connection that is already closed.
        return claims, verdicts

    def rejudge(self) -> list[Verdict]:
        """Re-judge every claim against the corpus as it stands now.

        A claim marked 'new' when the corpus was thin may be a restatement once the corpus
        has grown. Re-judging is cheap with embeddings, so a stale verdict is a choice
        rather than a constraint.
        """
        verdicts: list[Verdict] = []

        for row in list(self.store.iter_claims(self.pack.name)):
            claim = Claim(
                id=row["id"],
                pack=self.pack.name,
                source_id=row["source_id"],
                text=row["text"],
            )
            verdict = self.judge.judge_claim(claim)
            self.store.add_verdict(verdict)
            verdicts.append(verdict)
        return verdicts

    def close(self) -> None:
        self.store.close()
