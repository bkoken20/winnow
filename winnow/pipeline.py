"""Wiring: notes and media in, claims and verdicts out."""

from __future__ import annotations

import hashlib
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
from .models import Source, Verdict
from .packs import Pack, find_pack
from .store import Store

NOTE_EXTENSIONS = TEXT_EXTENSIONS


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
        return cls(config, store, pack, extractor, judge, llm)

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
        self.store.add_source(
            Source(id=sid, pack=self.pack.name, kind="note", path=str(path), title=path.stem)
        )
        claims = self.extractor.extract(text, sid)
        stored = 0
        for claim in claims:
            vector = self.judge.embedder.embed(claim.text)
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

        first_claims, unit_seconds = time_one(self.index_note, sample)
        projection = Projection(
            unit_seconds=unit_seconds,
            units=len(files),
            sample_bytes=sample.stat().st_size,
            total_bytes=total_bytes,
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
        try:
            frames = extract_frames(media, target / "frames")
        except FFmpegMissing:
            return ""
        if not frames:
            return ""

        prompt = self.pack.render_frame_prompt()
        if not prompt:
            return ""

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
            # The pack tells the model how to say "nothing here"; honour whatever token it
            # chose rather than hard-coding one, so a pack author is not silently ignored.
            if not text or text.strip("`\"' .").isupper():
                continue
            described.append(f"[{frame.seconds}s] {text}")
        return "\n".join(described)

    def ingest(
        self, target: Path, judge_claims: bool = True
    ) -> tuple[list["Claim"], list[Verdict]]:
        """Process one piece of material: transcript -> claims -> verdicts.

        Never acquires anything. `target` is a transcript file, a media file, or a folder
        that already holds one.
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
                f"{target}: {hint}. Winnow does not transcribe or download -- "
                "see docs/ACQUISITION.md for how to produce one."
            )

        sid = source_id_for(target)
        self.store.add_source(
            Source(
                id=sid,
                pack=self.pack.name,
                kind="media",
                path=str(target),
                title=target.stem,
            )
        )

        # Judging one item is a matter of minutes, so it runs the thorough pass list even
        # when indexing does not: three passes take a 20-minute talk from 39% coverage to
        # 92% for about three extra minutes, while the same choice on a 7.5 MB corpus is
        # 11.6 hours against 34.8 (experiments/TWO_PASS.md).
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
        if judge_claims:
            verdicts = [self.judge.judge_claim(c, v) for c, v in zip(claims, vectors)]

        # PHASE 2 -- store. Near-duplicate suppression belongs here as much as on the
        # indexing path, and more so: multi-pass extraction is the default for ingest and
        # reliably produces rewordings of one assertion. Suppression governs what is KEPT,
        # never what the reader is told -- every extracted claim keeps the verdict decided
        # above whether or not the corpus stores it.
        stored_vectors: list[list[float]] = []
        stored_ids: set[str] = set()
        for claim, vector in zip(claims, vectors):
            if self.is_near_duplicate(vector) or self._duplicates_within_batch(
                vector, stored_vectors
            ):
                continue
            self.store.add_claim(claim, vector, self.judge.embedder.name)
            stored_vectors.append(vector)
            stored_ids.add(claim.id)

        # Verdicts carry a foreign key to claims, so only those actually stored are written.
        for verdict in verdicts:
            if verdict.claim_id in stored_ids:
                self.store.add_verdict(verdict)

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
        from .models import Claim  # local import keeps the module graph shallow

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
