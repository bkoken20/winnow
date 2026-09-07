"""The three enforced behaviours in winnow.llm.

Each of these tests exists because the behaviour it checks is invisible when broken: the
pipeline keeps running and simply produces nothing, or produces plausible nonsense. Each
test was confirmed to fail when the behaviour is removed -- see tests/PERTURBATION.md.
"""

import json
import urllib.error

import pytest

from winnow.llm import ContextWindowNotSet, OllamaClient, OllamaError


class FakeTransport:
    """Stands in for ONE raw HTTP round trip.

    It replaces `_fetch`, deliberately not `_post`: `_post` owns the retry loop, so
    substituting it would delete the behaviour these tests exist to check and they would
    pass regardless of what the code did.
    """

    def __init__(self, response=None, fail_times=0, fail_status=429):
        self.bodies = []
        self.response = response or {"response": "ok"}
        self.fail_times = fail_times
        self.fail_status = fail_status
        self.calls = 0

    def __call__(self, url, data):
        self.calls += 1
        self.bodies.append(json.loads(data.decode("utf-8")))
        if self.calls <= self.fail_times:
            raise urllib.error.HTTPError(url, self.fail_status, "throttled", {}, None)
        return self.response


def client_with(transport) -> OllamaClient:
    client = OllamaClient(backoff_seconds=0.0)
    client._fetch = transport  # noqa: SLF001 - the round trip is the seam
    return client


# -- 1. num_ctx is always set --------------------------------------------------


def test_generate_sets_num_ctx_in_options():
    transport = FakeTransport()
    client = client_with(transport)
    client.generate("m", "prompt", num_ctx=32768)
    assert transport.bodies[0]["options"]["num_ctx"] == 32768


def test_generate_refuses_missing_context_window():
    client = client_with(FakeTransport())
    with pytest.raises(ContextWindowNotSet):
        client.generate("m", "prompt", num_ctx=0)


def test_num_ctx_has_no_default():
    """It must be impossible to generate without deciding the context window."""
    client = client_with(FakeTransport())
    with pytest.raises(TypeError):
        client.generate("m", "prompt")  # no num_ctx


# -- 2. JSON is never forced on prose calls ------------------------------------


def test_prose_call_does_not_set_format():
    transport = FakeTransport()
    client = client_with(transport)
    client.generate("m", "describe this", num_ctx=8192, as_json=False)
    assert "format" not in transport.bodies[0]


def test_json_call_sets_format():
    transport = FakeTransport()
    client = client_with(transport)
    client.generate("m", "give me json", num_ctx=8192, as_json=True)
    assert transport.bodies[0]["format"] == "json"


def test_describe_image_never_forces_json():
    transport = FakeTransport()
    client = client_with(transport)
    client.describe_image("vision", "what is here?", "BASE64", num_ctx=8192)
    body = transport.bodies[0]
    assert "format" not in body
    assert body["images"] == ["BASE64"]


# -- 3. transient failures are retried -----------------------------------------


@pytest.mark.parametrize("status", [403, 429, 503])
def test_transient_status_is_retried(status):
    transport = FakeTransport(fail_times=1, fail_status=status)
    client = client_with(transport)
    assert client.generate("m", "p", num_ctx=1024) == "ok"
    assert transport.calls == 2


def test_permanent_status_is_not_retried():
    transport = FakeTransport(fail_times=1, fail_status=404)
    client = client_with(transport)
    with pytest.raises(OllamaError):
        client.generate("m", "p", num_ctx=1024)
    assert transport.calls == 1


def test_gives_up_after_max_retries():
    transport = FakeTransport(fail_times=99, fail_status=429)
    client = client_with(transport)
    with pytest.raises(OllamaError):
        client.generate("m", "p", num_ctx=1024)
    assert transport.calls == client.max_retries


# -- errors must carry the server's own explanation ----------------------------


def test_embedding_failure_reports_the_servers_reason():
    """A server started without embedding support is the actionable detail, not 'no embedding'.

    Observed for real: Ollama replies 200 with
    {"error": "This server does not support embeddings. Start it with `--embeddings`"}.
    Swallowing that sends the user off changing models, which cannot possibly help.
    """
    transport = FakeTransport(
        response={"error": "This server does not support embeddings. Start it with `--embeddings`"}
    )
    client = client_with(transport)
    with pytest.raises(OllamaError) as exc:
        client.embed("nomic-embed-text", "some text")
    assert "--embeddings" in str(exc.value)


def test_embedding_failure_without_a_reason_still_raises():
    client = client_with(FakeTransport(response={}))
    with pytest.raises(OllamaError):
        client.embed("m", "text")
