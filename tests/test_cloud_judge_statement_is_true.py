"""The privacy statement described a transport that does not exist.

With `judge_location: "cloud"`, a judge model set, and `ollama_host` at its default
localhost, `winnow status` printed:

    NOT FULLY LOCAL. a cloud judge ('qwen2.5:14b-instruct') is declared, so the text of
    each claim judged, plus the most similar claims from your corpus, is sent to it.

Nothing is sent to anything. The judge is `OllamaClient(host=config.ollama_host)`, the host
is this machine, and Winnow has no cloud API client of any kind. The README names `winnow
status` as the authority on this question, so a false sentence there is worse than no
sentence -- and it is false in the alarming direction, which trains people to disbelieve the
warning that matters.

`judge_location` is a DECLARATION. It routes nothing. It is worth having precisely because
`ollama_host` can be local-looking and forward elsewhere -- a tunnel, or the proxy variables
`urllib` honours -- and only the person running it knows. So the statement has to say what it
is: your declaration about a host, not a second destination Winnow sends to.

The stored lineage had the same fault. `JudgeStamp` recorded `judge_location='cloud'` and
nothing about the host, so a verdict cannot answer the one question the stamp exists for:
did this text leave the machine?

Reported by an external review.
"""
from __future__ import annotations

import json
from dataclasses import asdict

from winnow.config import Config
from winnow.judge import Judge, JudgeConfig
from winnow.models import JudgeStamp

REMOTE = "http://box.example:11434"


def _statement(**overrides) -> str:
    return Config(**overrides).egress_statement()


# -- the statement -----------------------------------------------------------------------


def test_a_declared_cloud_judge_on_a_local_host_does_not_claim_a_transport():
    said = _statement(judge_location="cloud", judge_model="qwen2.5:14b-instruct")

    assert "is sent to it" not in said, (
        f"nothing is sent to anything -- the judge runs against ollama_host: {said!r}"
    )
    assert "ollama_host" in said, (
        f"say what actually decides the destination: {said!r}"
    )


def test_it_still_says_the_material_leaves_when_you_have_declared_that():
    """Not the opposite mistake. A declaration is a claim about the world; believe it."""
    said = _statement(judge_location="cloud", judge_model="qwen2.5:14b-instruct")

    assert "NOT FULLY LOCAL" in said
    assert "declar" in said.lower(), f"name it as your declaration: {said!r}"


def test_a_remote_host_is_not_described_as_two_separate_destinations():
    """`ollama_host` already carries everything. The judge is not a second recipient."""
    said = _statement(
        judge_location="cloud", judge_model="qwen2.5:14b-instruct", ollama_host=REMOTE
    )

    assert said.count("box.example") >= 1
    assert "is sent to it" not in said, (
        f"the judge is the same host, not another one: {said!r}"
    )


def test_a_local_declaration_with_a_remote_host_still_warns():
    """The guard: the declaration must not be able to talk the warning down."""
    said = _statement(
        judge_location="local", judge_model="qwen2.5:14b-instruct", ollama_host=REMOTE
    )

    assert "NOT FULLY LOCAL" in said
    assert "box.example" in said


def test_a_cloud_declaration_without_a_judge_still_says_it_does_nothing():
    said = _statement(judge_location="cloud")

    assert "NOT FULLY LOCAL" in said
    assert "judge_model" in said


def test_a_plain_local_setup_is_still_reported_local():
    """The mirror: a statement that always warns is a statement nobody reads."""
    assert Config().is_fully_local
    assert "LOCAL, except fetching" in Config().egress_statement()


# -- the lineage -------------------------------------------------------------------------


def _stamp(**overrides) -> JudgeStamp:
    config = Config(**overrides)

    class _Embedder:
        name = "nomic-embed-text"
        backend = "ollama"

        def embed(self, text):
            return [0.0]

    judge = Judge(
        store=None,
        embedder=_Embedder(),
        config=JudgeConfig(
            pack="ai_tooling",
            pack_version="1",
            min_corpus=25,
            judge_model=config.judge_model,
            judge_location=config.judge_location,
            judge_num_ctx=config.judge_num_ctx,
            stayed_on_this_machine=config.material_stays_local,
        ),
        llm=object() if config.judge_model else None,
    )
    return judge.stamp()


def test_the_stamp_records_whether_the_material_stayed_here():
    """The one question the stamp exists to answer, and it could not.

    `judge_location` is a declaration; the transport is `ollama_host`. A verdict carrying
    only the declaration cannot tell a later reader whether the text left the machine.
    """
    local = _stamp(judge_model="m")
    remote = _stamp(judge_model="m", ollama_host=REMOTE)

    assert local.stayed_on_this_machine is True
    assert remote.stayed_on_this_machine is False


def test_a_declared_tunnel_is_recorded_as_having_left():
    """A loopback address the user says forwards. The address alone cannot see this."""
    stamp = _stamp(judge_model="m", judge_location="cloud")

    assert stamp.judge_location == "cloud", "the declaration is still recorded as itself"
    assert stamp.stayed_on_this_machine is False, (
        "the address is local and the user says it forwards -- believe the user"
    )


def test_tier_zero_keeps_the_declaration_that_tier_zero_erases():
    """Found by walking the stamp, not by running it.

    `judge_location` is blanked at tier 0 because no judge ran. The user's correction to a
    tunnelled host lived ONLY in that field, so a tier-0 verdict recorded an empty
    declaration and a local-looking address -- and read back as "never left the machine"
    while embeddings were going through the tunnel exactly as judging would have.

    Walked, before the fix:

        host        declared  tier  judge_location  stayed
        localhost   cloud     0     ''              True
    """
    stamp = _stamp(judge_location="cloud")  # no judge_model, so tier 0

    assert stamp.tier == 0
    assert stamp.judge_location == "", "no judge ran, so there is no judge location"
    assert stamp.stayed_on_this_machine is False, (
        "embeddings went to the same tunnelled host, and the verdict must say so"
    )


def test_a_stamp_from_an_older_corpus_still_loads():
    """The field is additive: verdicts written before it exist and must stay readable."""
    old = json.loads(
        '{"tier": 1, "embed_model": "nomic-embed-text", "embed_backend": "ollama",'
        ' "judge_model": "m", "judge_location": "local", "prompt_version": "1",'
        ' "pack_version": "1"}'
    )
    stamp = JudgeStamp(**old)

    assert stamp.stayed_on_this_machine is None, "unrecorded is not the same as stayed"


def test_the_stamp_serialises_the_new_field():
    stamp = _stamp(judge_model="m", ollama_host=REMOTE)
    written = json.dumps(asdict(stamp))

    assert '"stayed_on_this_machine": false' in written


def test_tier_zero_records_it_too():
    """Embeddings go to the same host, so the question applies with no judge at all."""
    stamp = _stamp(ollama_host=REMOTE)

    assert stamp.tier == 0
    assert stamp.stayed_on_this_machine is False
