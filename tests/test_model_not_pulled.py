"""The likeliest first-run failure got the wrong advice, and the right answer was discarded.

A stranger installs Winnow, starts Ollama, and runs `winnow index` before pulling the models.
Ollama is running perfectly and answers:

    404  {"error": "model 'qwen2.5:14b-instruct' not found"}

Winnow reduced that to "returned HTTP 404" -- dropping the one sentence that says what is
wrong -- and then advised:

    Is it running? Check with: curl -s http://localhost:11434/api/tags

which sends them to verify the thing that is already fine, while the actual fix
(`ollama pull qwen2.5:14b-instruct`) appears nowhere. The README lists the pulls, but nobody
re-reads an install section when a command fails; they read the error.

Verified against a live Ollama before the fix.
"""
from __future__ import annotations

import io
import json
import urllib.error

import pytest

from winnow.llm import OllamaClient, OllamaError


def _http_error(status: int, body: dict) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="http://localhost:11434/api/generate",
        code=status,
        msg="err",
        hdrs=None,
        fp=io.BytesIO(json.dumps(body).encode("utf-8")),
    )


def _client_raising(error) -> OllamaClient:
    client = OllamaClient(max_retries=1)

    def fetch(url, data):
        raise error

    client._fetch = fetch  # the single raw round trip; retry logic stays above it
    return client


def test_the_servers_own_explanation_survives():
    client = _client_raising(
        _http_error(404, {"error": "model 'qwen2.5:14b-instruct' not found"})
    )
    with pytest.raises(OllamaError) as exc:
        client.generate("qwen2.5:14b-instruct", "x", num_ctx=4096)

    message = str(exc.value)
    assert "not found" in message, (
        f"the server said what was wrong and it was discarded. Message was: {message!r}"
    )
    assert "qwen2.5:14b-instruct" in message, "and which model it was about"


def test_the_error_carries_the_status_so_a_caller_can_advise_correctly():
    client = _client_raising(_http_error(404, {"error": "model 'm' not found"}))
    with pytest.raises(OllamaError) as exc:
        client.generate("m", "x", num_ctx=4096)
    assert getattr(exc.value, "status", None) == 404, (
        "the CLI cannot tell 'not pulled' from 'not running' without the status"
    )


def test_a_missing_model_is_told_to_pull_it_not_to_check_the_server(capsys):
    from winnow import cli

    def failing(args):
        raise OllamaError("model 'qwen2.5:14b-instruct' not found", status=404)

    code = cli._run(failing, args=None)
    said = capsys.readouterr().err.lower()

    assert code == 4
    assert "ollama pull" in said, (
        f"a 404 means the model is not pulled; advice was: {said!r}"
    )
    assert "is it running" not in said, (
        "Ollama answered, so it is running -- telling them to check that wastes the one "
        "moment they are looking at the error"
    )


def test_a_server_that_is_actually_down_still_says_so(capsys):
    from winnow import cli

    def failing(args):
        raise OllamaError("http://localhost:11434/api/generate failed after 3 attempts")

    code = cli._run(failing, args=None)
    said = capsys.readouterr().err.lower()

    assert code == 4
    assert "is it running" in said, "with no status, the server being down is the likely cause"
