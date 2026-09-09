"""`http_proxy` silently redirected requests Winnow calls local.

`urllib` reads the proxy environment variables and does not bypass loopback on its own.
Measured: a listener standing in for a proxy, `http_proxy` pointed at it, and a normal
`OllamaClient(host="http://localhost:11434").embed(...)`:

    fake proxy received: POST http://localhost:11434/api/embeddings HTTP/1.1
    embed() returned   : [0.1, 0.2]

Two failures in one. The text left the machine while `winnow status` printed "LOCAL, except
fetching ... never transmitted" — and the vector came back from the proxy, not from Ollama,
so the result was wrong as well as leaked. Winnow could not tell the difference.

A loopback address has no legitimate reason to be proxied. An SSH tunnel binds a local port
directly and involves no proxy, so refusing the proxy for loopback does not break the
forwarded-host case that `judge_location: "cloud"` exists for.

When the host is genuinely remote, a configured proxy is a real additional recipient of every
claim and transcript, and the privacy statement names it.

Reported by an external review.
"""
from __future__ import annotations

import socket
import threading

import pytest

from winnow.config import Config
from winnow.llm import OllamaClient


class _Listener:
    """Stands in for a proxy: records what arrives, answers so nothing hangs."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.received: list[str] = []
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        try:
            conn, _ = self.sock.accept()
        except OSError:
            return
        with conn:
            data = conn.recv(4096)
            self.received.append(
                data.decode("latin-1").splitlines()[0] if data else "(empty)"
            )
            conn.sendall(
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                b'Content-Length: 25\r\n\r\n{"embedding": [0.1, 0.2]}'
            )

    def close(self):
        self.sock.close()


@pytest.fixture
def listener():
    made = _Listener()
    yield made
    made.close()


def test_a_proxy_does_not_receive_a_request_meant_for_localhost(listener, monkeypatch):
    monkeypatch.setenv("http_proxy", f"http://127.0.0.1:{listener.port}")
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.delenv("NO_PROXY", raising=False)

    client = OllamaClient(host="http://127.0.0.1:1", timeout=2, max_retries=1)
    with pytest.raises(Exception):
        # Nothing listens on port 1, so this must fail by not connecting -- NOT by being
        # quietly answered by the proxy.
        client.embed("nomic-embed-text", "a claim about throughput")

    assert listener.received == [], (
        f"a request for a loopback address was sent to the proxy: {listener.received}"
    )


def test_the_answer_does_not_come_from_the_proxy(listener, monkeypatch):
    """The half that is not about privacy: a proxy's reply is not Ollama's reply."""
    monkeypatch.setenv("http_proxy", f"http://127.0.0.1:{listener.port}")
    monkeypatch.delenv("no_proxy", raising=False)

    client = OllamaClient(host="http://127.0.0.1:1", timeout=2, max_retries=1)
    with pytest.raises(Exception):
        client.embed("nomic-embed-text", "text")

    assert listener.received == [], "the vector would have been the proxy's invention"


@pytest.mark.parametrize(
    "host",
    ["http://localhost:11434", "http://127.0.0.1:11434", "http://[::1]:11434"],
    ids=["localhost", "127.0.0.1", "ipv6 loopback"],
)
def test_every_spelling_of_loopback_is_covered(host, monkeypatch, listener):
    monkeypatch.setenv("http_proxy", f"http://127.0.0.1:{listener.port}")
    monkeypatch.delenv("no_proxy", raising=False)

    client = OllamaClient(host=host, timeout=2, max_retries=1)
    assert client.bypasses_proxy is True, f"{host} would be proxied"


@pytest.mark.parametrize(
    "host",
    [
        "http://not-localhost:11434",
        "http://evil.localhost:11434",
        "http://localhost.evil.example:11434",
        "http://127.0.0.1.evil.example:11434",
    ],
    ids=["not-localhost", "evil.localhost", "localhost.evil", "127.0.0.1.evil"],
)
def test_a_name_that_merely_resembles_loopback_is_not_loopback(host):
    """Exact match, not a prefix or a suffix.

    A suffix rule (`endswith`) survived the perturbation battery because the only lookalike
    tested was a PREFIX -- `localhost.evil.example`. `not-localhost` and `evil.localhost`
    both end in "localhost" and neither is verifiably this machine. A check that decides
    whether text leaves the machine fails closed on anything it cannot be certain of.
    """
    from winnow.config import is_loopback_host

    assert is_loopback_host(host) is False
    assert OllamaClient(host=host).bypasses_proxy is False


def test_a_remote_host_still_honours_the_proxy(monkeypatch):
    """The guard: a proxy is how many networks reach anything at all."""
    monkeypatch.setenv("http_proxy", "http://proxy.example:3128")

    client = OllamaClient(host="http://box.example:11434")
    assert client.bypasses_proxy is False, (
        "refusing the proxy for a remote host would break the setups that need one"
    )


def test_the_privacy_statement_names_the_proxy_for_a_remote_host(monkeypatch):
    monkeypatch.setenv("http_proxy", "http://proxy.example:3128")

    said = Config(ollama_host="http://box.example:11434").egress_statement()

    assert "proxy.example" in said, (
        f"a third party receives every claim and the statement does not name it: {said!r}"
    )


def test_the_privacy_statement_is_silent_about_a_proxy_it_bypasses(monkeypatch):
    """A warning that fires on every corporate laptop is a warning nobody reads."""
    monkeypatch.setenv("http_proxy", "http://proxy.example:3128")

    said = Config().egress_statement()

    assert "proxy.example" not in said
    assert "LOCAL, except fetching" in said
