"""Storage round-trips, privacy statements, and pack loading."""

import json
from pathlib import Path

import pytest

from winnow.config import Config
from winnow.embed import HashingEmbedder, build_embedder, cosine_similarity
from winnow.models import Claim, Coverage, JudgeStamp, Neighbour, Source, Verdict
from winnow.packs import find_pack
from winnow.store import Store

REPO_ROOT = Path(__file__).resolve().parent.parent


# -- store ---------------------------------------------------------------------


def seed(store: Store, embedder, texts):
    store.add_source(Source(id="s1", pack="p", kind="note", path="/n"))
    for i, text in enumerate(texts):
        store.add_claim(
            Claim(id=f"c{i}", pack="p", source_id="s1", text=text),
            embedder.embed(text),
            embedder.name,
        )


def test_claims_round_trip(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    embedder = HashingEmbedder()
    seed(store, embedder, ["alpha beta", "gamma delta"])
    assert store.count_claims("p") == 2
    assert store.count_claims("other") == 0


def test_similarity_search_finds_the_closest_claim(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    embedder = HashingEmbedder()
    seed(store, embedder, ["context window truncation", "unrelated cooking recipe"])
    hits = store.similarity_search("p", embedder.embed("context window truncation"))
    assert hits[0].text == "context window truncation"
    assert hits[0].similarity > 0.99


def test_similarity_search_excludes_the_claim_itself(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    embedder = HashingEmbedder()
    seed(store, embedder, ["only claim here"])
    hits = store.similarity_search("p", embedder.embed("only claim here"), exclude_claim_id="c0")
    assert hits == []


def test_verdicts_round_trip(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    embedder = HashingEmbedder()
    seed(store, embedder, ["a claim"])
    verdict = Verdict(
        claim_id="c0",
        novelty="new",
        similarity=0.1,
        neighbours=[Neighbour(claim_id="c0", similarity=0.1, text="a claim")],
        coverage=Coverage(corpus_claims=1, min_for_verdict=1),
        judge=JudgeStamp(tier=0, embed_model="hashing-256", embed_backend="hashing"),
    )
    store.add_verdict(verdict)
    rows = store.latest_verdicts("p")
    assert len(rows) == 1
    assert json.loads(rows[0]["judge_json"])["embed_backend"] == "hashing"


def test_invalid_novelty_is_rejected():
    with pytest.raises(ValueError):
        Verdict(
            claim_id="x",
            novelty="probably-new-ish",
            similarity=0.0,
            neighbours=[],
            coverage=Coverage(1, 1),
            judge=JudgeStamp(tier=0, embed_model="m", embed_backend="ollama"),
        )


# -- embedders -----------------------------------------------------------------


def test_hashing_embedder_is_deterministic():
    a, b = HashingEmbedder(), HashingEmbedder()
    assert a.embed("same text") == b.embed("same text")


def test_identical_text_is_maximally_similar():
    e = HashingEmbedder()
    assert cosine_similarity(e.embed("hello world"), e.embed("hello world")) == pytest.approx(1.0)


def test_unknown_backend_is_refused():
    with pytest.raises(ValueError):
        build_embedder("magic")


def test_ollama_embedder_does_not_silently_fall_back():
    """A failing real embedder must raise, never degrade to meaningless hashing."""
    from winnow.embed import OllamaEmbedder
    from winnow.llm import OllamaError

    class DeadClient:
        def embed(self, model, text):
            raise OllamaError("no server")

    with pytest.raises(OllamaError):
        OllamaEmbedder(model="m", client=DeadClient()).embed("text")


# -- config and privacy --------------------------------------------------------


def test_default_config_is_fully_local():
    config = Config()
    assert config.is_fully_local
    assert "FULLY LOCAL" in config.egress_statement()
    assert "never transmitted" in config.egress_statement()


def test_cloud_judge_produces_an_explicit_egress_warning():
    config = Config(judge_model="remote-model", judge_location="cloud")
    statement = config.egress_statement()
    assert not config.is_fully_local
    assert "NOT FULLY LOCAL" in statement
    assert "remote-model" in statement
    assert "corpus" in statement  # says what of the user's data is sent


def test_a_remote_ollama_host_is_not_fully_local():
    """The privacy statement must account for where the model server actually is.

    Everything -- transcripts, notes, every extracted claim -- is POSTed to `ollama_host`.
    Reporting "nothing leaves this machine" while that points at another box is worse than
    reporting nothing at all.
    """
    config = Config(ollama_host="http://192.168.1.50:11434")
    assert not config.host_is_local
    assert not config.is_fully_local
    statement = config.egress_statement()
    assert "NOT FULLY LOCAL" in statement
    assert "192.168.1.50" in statement
    assert "EVERYTHING" in statement


@pytest.mark.parametrize(
    "host", ["http://localhost:11434", "http://127.0.0.1:11434", "http://[::1]:11434"]
)
def test_loopback_hosts_are_local(host):
    assert Config(ollama_host=host).host_is_local


@pytest.mark.parametrize(
    "host",
    [
        "ollama.example.com:11434",  # no scheme -- urlparse finds no hostname at all
        "not-a-url",
        "",
        "://broken",
    ],
)
def test_an_unreadable_host_is_never_called_local(host):
    """The privacy check must fail CLOSED.

    `ollama.example.com:11434` is an ordinary thing to write and parses to no hostname,
    which an earlier version treated as loopback -- so the tool announced "FULLY LOCAL.
    Nothing leaves this machine" for a remote server. A privacy statement that fails open
    is worse than none, because the user reads it and believes it.
    """
    config = Config(ollama_host=host)
    assert not config.host_is_local
    assert not config.is_fully_local
    assert "FULLY LOCAL" not in config.egress_statement().replace("NOT FULLY LOCAL", "")


def test_an_unreadable_host_says_how_to_fix_it():
    statement = Config(ollama_host="ollama.example.com:11434").egress_statement()
    assert "cannot be read as a URL" in statement
    assert "http://localhost:11434" in statement


def test_cloud_judge_location_without_a_model_says_it_does_nothing():
    """A declared cloud judge with no model configured judges nothing at all."""
    statement = Config(judge_location="cloud").egress_statement()
    assert "does nothing" in statement


def test_unknown_config_keys_warn_rather_than_vanish(tmp_path):
    """A typo used to become a silently-applied default.

    Worst for `text_num_ctx`, where the default truncates every prompt and extraction then
    reports finding nothing -- no error anywhere.
    """
    path = tmp_path / "winnow.json"
    path.write_text('{"text_numctx": 4096, "pack": "ai_tooling"}', encoding="utf-8")

    with pytest.warns(UserWarning, match="text_numctx"):
        config = Config.load(path)

    assert config.text_num_ctx == 32768  # still the default, but no longer silently


def test_unknown_key_warning_suggests_the_intended_setting(tmp_path):
    path = tmp_path / "winnow.json"
    path.write_text('{"chunk_char": 500}', encoding="utf-8")
    with pytest.warns(UserWarning, match="did you mean 'chunk_chars'"):
        Config.load(path)


def test_a_correct_config_warns_about_nothing(tmp_path):
    import warnings as _w

    path = tmp_path / "winnow.json"
    Config(pack="ai_tooling").save(path)
    with _w.catch_warnings():
        _w.simplefilter("error")
        Config.load(path)


def test_config_round_trips(tmp_path):
    path = tmp_path / "winnow.json"
    Config(pack="ai_tooling", text_num_ctx=16384).save(path)
    assert Config.load(path).text_num_ctx == 16384


def test_missing_config_gives_defaults(tmp_path):
    assert Config.load(tmp_path / "absent.json").pack == "ai_tooling"


# -- packs ---------------------------------------------------------------------


def test_shipped_pack_loads():
    pack = find_pack("ai_tooling", REPO_ROOT / "packs")
    assert pack.name == "ai_tooling"
    assert "__TEXT__" in pack.extract_prompt
    assert pack.min_corpus > 0
    assert pack.starter_sources


def test_pack_prompt_rendering_substitutes_text():
    pack = find_pack("ai_tooling", REPO_ROOT / "packs")
    rendered = pack.render_extract_prompt("THE SOURCE")
    assert "THE SOURCE" in rendered
    assert "__TEXT__" not in rendered


def test_frame_prompt_asks_for_prose_not_json():
    """A frame prompt that asked for JSON would trip the forced-format bug."""
    pack = find_pack("ai_tooling", REPO_ROOT / "packs")
    assert "NO_TECHNICAL_CONTENT" in pack.frame_prompt
    assert "json" not in pack.frame_prompt.lower()


def test_missing_pack_names_what_is_available(tmp_path):
    with pytest.raises(FileNotFoundError) as exc:
        find_pack("nonexistent", REPO_ROOT / "packs")
    assert "ai_tooling" in str(exc.value)
