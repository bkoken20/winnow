"""The privacy section is a claim about the whole repository, not about winnow/.

It named one outbound path: yt-dlp. Four others exist and none were mentioned --
`scripts/fetch_starter_corpus.py` runs `git clone` against public repositories, the
documented install runs `pip install -U yt-dlp` against a package index, every model call
goes to `ollama_host` which is only local because it defaults to localhost, and
`judge_location` is a DECLARATION that routes nothing at all.

That last one is the same fault as `embed_backend: "cloud"`. The privacy statement describes
what a cloud judge would transmit; the judge is `OllamaClient(host=config.ollama_host)`
whatever `judge_location` says. What decides where claims go is `ollama_host` and nothing
else. And `judge_location` was compared with `!= "cloud"`, so a typo -- `"cloutd"`,
`"Cloud"` -- read as fully local: a privacy check failing OPEN, which this codebase refuses
to do everywhere else it is stated.

Reported by an external review.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from winnow import cli
from winnow.config import JUDGE_LOCATIONS, Config

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
PACKS_ROOT = ROOT / "packs"

# Every file that reaches outside this machine, and the word the README must use for it.
# Files that shell out to a LOCAL tool are listed with None, so that adding one forces a
# decision here rather than passing unnoticed.
OUTBOUND = {
    "winnow/llm.py": "ollama_host",
    "winnow/acquire.py": "yt-dlp",
    "scripts/fetch_starter_corpus.py": "git clone",
    "winnow/media.py": None,  # ffmpeg, on this machine
    # `getproxies()` only, to disclose a proxy in the path. It reads environment
    # variables and, on Windows, the registry -- verified to open no socket.
    "winnow/config.py": None,
}


def _privacy_section() -> str:
    start = README.index("## Privacy")
    end = README.index("\n## ", start + 1)
    return README[start:end]


def _code_only(path: Path) -> str:
    """The file with comments and string literals removed.

    A comment that mentions a socket is not a socket. This check refused `winnow/cli.py`
    because a comment there describes a traceback that used to end "in a sleep or a socket
    read" -- the sixth time in this repository that a check has found my own prose, and the
    second in one day: the markdown link checks did it this morning and were fixed by
    scanning prose with code removed. This is the mirror.

    `tokenize` rather than a regular expression, because it knows where a string ends and a
    pattern only guesses.
    """
    import io
    import tokenize

    source = path.read_text(encoding="utf-8")
    lines = source.splitlines(keepends=True)
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # A file this cannot parse is a bigger problem than this test, and pyflakes will
        # say so. Fall back to the whole text rather than silently scanning nothing.
        return source

    # Blank the spans IN PLACE. Joining the surviving tokens with spaces was the first
    # attempt and it broke adjacency -- `subprocess.run` became `subprocess . run`, so the
    # pattern matched nothing and the check would have passed on any repository at all.
    # Every other character keeps its column this way.
    for token in tokens:
        if token.type not in (tokenize.COMMENT, tokenize.STRING):
            continue
        (start_row, start_col), (end_row, end_col) = token.start, token.end
        for row in range(start_row - 1, end_row):
            line = lines[row]
            begin = start_col if row == start_row - 1 else 0
            finish = end_col if row == end_row - 1 else len(line)
            lines[row] = line[:begin] + " " * (finish - begin) + line[finish:]
    return "".join(lines)


def _files_that_could_reach_out() -> set[str]:
    """Anything that opens a URL or runs another program. Deliberately over-broad."""
    found = set()
    for folder in ("winnow", "scripts"):
        for path in sorted((ROOT / folder).glob("*.py")):
            code = _code_only(path)
            if re.search(r"urllib\.request|http\.client|\bsocket\b|subprocess\.(run|Popen)", code):
                found.add(f"{folder}/{path.name}")
    return found


def test_the_scanner_reads_code_and_not_comments(tmp_path):
    """Guard the guard, in both directions.

    A scanner that stripped too much would find nothing and this whole check would pass on
    any repository at all.
    """
    talks_about_it = tmp_path / "talks.py"
    talks_about_it.write_text(
        "# this module once used a socket and subprocess.run\n"
        'MESSAGE = "we do not call urllib.request here"\n'
        "VALUE = 1\n",
        encoding="utf-8",
    )
    does_it = tmp_path / "does.py"
    does_it.write_text("import subprocess\nsubprocess.run(['ls'])\n", encoding="utf-8")

    pattern = r"urllib\.request|http\.client|\bsocket\b|subprocess\.(run|Popen)"
    assert not re.search(pattern, _code_only(talks_about_it)), "a comment was read as code"
    assert re.search(pattern, _code_only(does_it)), "real code was stripped away"


def test_the_list_of_outbound_paths_is_complete():
    """A new module that shells out or opens a URL must be classified, not discovered later."""
    actual = _files_that_could_reach_out()
    unlisted = sorted(actual - set(OUTBOUND))

    assert not unlisted, (
        f"{unlisted} can run another program or open a URL and this test has never been "
        "told whether that reaches the network. Add it to OUTBOUND -- with None if the "
        "program it runs is local."
    )


@pytest.mark.parametrize(
    "path, word",
    [(p, w) for p, w in OUTBOUND.items() if w],
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_the_privacy_section_names_every_outbound_path(path, word):
    assert word in _privacy_section(), (
        f"{path} reaches the network and the privacy section never says {word!r}"
    )


def test_the_privacy_section_covers_the_package_index():
    """`pip install -U yt-dlp` is in the install instructions, so it is a path we shipped."""
    section = _privacy_section().lower()
    assert "package index" in section or "pypi" in section, (
        "the documented install contacts a package index and the privacy section is silent"
    )


def test_the_privacy_section_says_judge_location_routes_nothing():
    section = _privacy_section()
    assert "judge_location" in section, "the setting is not mentioned at all"
    assert "ollama_host" in section, (
        "the section must say what actually decides where claims go, which is ollama_host"
    )


# -- judge_location as a setting ---------------------------------------------------------


def test_an_unknown_judge_location_is_refused(tmp_path, capsys):
    config = tmp_path / "winnow.json"
    config.write_text(
        json.dumps(
            {
                "pack": "ai_tooling",
                "corpus_path": str(tmp_path / "corpus.db"),
                "embed_backend": "hashing",
                "packs_root": str(PACKS_ROOT),
                "judge_location": "cloutd",
            }
        ),
        encoding="utf-8",
    )

    code = cli.main(["status", "--config", str(config)])
    said = "".join(capsys.readouterr())

    assert "Traceback" not in said
    assert code == 2, f"a misspelt judge_location was accepted: {said!r}"
    assert "judge_location" in said and "cloutd" in said, said


def test_a_misspelt_judge_location_is_not_treated_as_local():
    """The check failed OPEN: anything but the exact string 'cloud' counted as local."""
    for invented in ("cloutd", "Cloud", "remote", ""):
        assert not Config(judge_location=invented, judge_model="m").is_fully_local, (
            f"judge_location={invented!r} is not a value Winnow understands, so where "
            "claims would go cannot be stated -- and an unstatable destination is not local"
        )


def test_the_documented_values_are_the_ones_that_load(tmp_path):
    for value in JUDGE_LOCATIONS:
        config = tmp_path / f"{value}.json"
        config.write_text(json.dumps({"judge_location": value}), encoding="utf-8")
        assert Config.load(config).judge_location == value


def test_a_not_local_verdict_always_says_why():
    """It printed "NOT FULLY LOCAL. ." -- a headline, a full stop, and nothing to act on.

    Failing closed on an unrecognised value created a case the reason list had no branch
    for. Anything that makes the verdict false has to produce a sentence, because the
    verdict alone tells the user to worry and not what to change.
    """
    cases = [
        Config(judge_location="cloutd"),
        Config(embed_backend="cloud"),
        Config(ollama_host="http://elsewhere.example:11434"),
        Config(ollama_host="ollama.example.com:11434"),
        Config(judge_location="cloud", judge_model="m"),
        Config(judge_location="cloud"),
    ]
    for config in cases:
        assert not config.is_fully_local, f"{config.judge_location}/{config.embed_backend}"
        statement = config.egress_statement()
        body = statement.removeprefix("NOT FULLY LOCAL.").strip(" .")
        assert len(body) > 20, f"no reason given: {statement!r}"


def test_every_setting_named_in_a_reason_is_a_real_setting():
    """A reason that names a setting the user cannot find is not actionable either."""
    fields = set(Config.__dataclass_fields__)
    for config in (Config(judge_location="cloutd"), Config(embed_backend="cloud")):
        statement = config.egress_statement()
        named = [f for f in fields if f in statement]
        assert named, f"the reason names no setting at all: {statement!r}"


@pytest.mark.parametrize(
    "config, setting, value",
    [
        (Config(judge_location="cloutd"), "judge_location", "cloutd"),
        (Config(embed_backend="cloud"), "embed_backend", "cloud"),
        (Config(ollama_host="http://elsewhere.example:11434"), "ollama_host", "elsewhere"),
    ],
    ids=["judge_location", "embed_backend", "ollama_host"],
)
def test_the_reason_names_the_setting_and_the_value_that_is_wrong(config, setting, value):
    """Generic beats empty, but only naming the offender tells the user what to edit.

    Without this, the specific branch and the catch-all fallback each pass the other's
    tests: remove either and a sentence is still produced, long enough and mentioning
    enough setting names to satisfy a looser assertion.
    """
    statement = config.egress_statement()

    assert setting in statement, f"which setting? {statement!r}"
    assert value in statement, f"which value? {statement!r}"


def test_a_verdict_with_no_written_reason_still_explains_itself(monkeypatch):
    """The fallback, tested on its own terms rather than through a case that has a branch.

    Today every way of making `is_fully_local` false has a sentence written for it, so the
    fallback is unreachable and nothing exercised it. It exists for the next setting added
    without one -- which is exactly the case that will not be noticed.
    """
    monkeypatch.setattr(type(Config()), "is_fully_local", property(lambda self: False))
    statement = Config().egress_statement()

    assert statement != "NOT FULLY LOCAL. .", "a headline, a full stop, and nothing to act on"
    body = statement.removeprefix("NOT FULLY LOCAL.").strip(" .")
    assert len(body) > 20, f"no reason given: {statement!r}"
    assert "winnow status" in body, "point at the command that can say more"


def test_local_is_still_local():
    """The guard: failing closed must not make everything read as non-local."""
    assert Config().is_fully_local
