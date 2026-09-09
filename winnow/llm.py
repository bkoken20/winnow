"""Ollama client for generation and embeddings.

Three hard-won behaviours are enforced here rather than left to callers. Each cost a real
debugging session to find, each is invisible when wrong, and each has a test that fails if
it is removed.

1. `num_ctx` is ALWAYS set explicitly. Ollama silently defaults to a small context window
   (~2-4k tokens) regardless of the model's real capacity. A long transcript is then
   truncated with no error, no warning, and no partial result -- extraction simply returns
   nothing, which reads as "there was nothing in this material" rather than "the input was
   cut off". This is the single most expensive bug in this domain.

2. JSON format is NEVER forced on a prompt that asks for prose. Vision/description prompts
   want sentences; forcing `format: "json"` on them makes the model fight the constraint
   and emit garbled, hallucinated output (invented numbers, malformed nesting). The flag is
   per call, never global.

3. Transient HTTP failures are retried. A 429 or 503 from a busy model server is usually a
   throttle or a model still loading, not a real failure.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from .config import is_loopback_host
from dataclasses import dataclass

DEFAULT_HOST = "http://localhost:11434"

# Retried rather than raised. 403 is included because upstreams commonly use it for
# throttling, not only for genuine authorisation failures.
TRANSIENT_STATUS = (403, 429, 500, 502, 503, 504)


class OllamaError(RuntimeError):
    """A failure talking to the model server, carrying the server's own account of it.

    `status` is the HTTP status when there was one, so a caller can distinguish "the server
    is not there" from "the server is fine and the model is not pulled" -- two failures with
    completely different fixes that used to produce identical advice.
    """

    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


def _detail(exc: urllib.error.HTTPError) -> str:
    """The server's own message, if it sent one. Never raises: this runs inside error handling."""
    try:
        body = exc.read().decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - a failure to read the body must not mask the error
        return ""
    try:
        message = json.loads(body).get("error")
    except (json.JSONDecodeError, AttributeError):
        message = body.strip()[:200] or None
    return f" -- {message}" if message else ""


class ContextWindowNotSet(ValueError):
    """Raised when a caller tries to generate without declaring a context window.

    Deliberately fatal. A silently-truncated prompt produces a plausible-looking empty
    result, which is far worse than a crash.
    """


@dataclass
class OllamaClient:
    host: str = DEFAULT_HOST
    timeout: int = 600
    max_retries: int = 3
    backoff_seconds: float = 2.0

    # -- transport -------------------------------------------------------------
    # The seam is `_fetch`: ONE raw round trip, no retry logic. Retrying lives in `_post`,
    # above it. This split matters for more than tidiness -- when the substitution point
    # was `_post`, replacing it in a test also replaced the retry behaviour, so the retry
    # tests exercised the fake rather than this module and passed no matter what the code
    # did. A test that cannot fail is not evidence.

    @property
    def bypasses_proxy(self) -> bool:
        """A loopback address is never proxied, whatever the environment says.

        `urllib` reads `http_proxy` and does not bypass loopback on its own. Measured with a
        listener standing in for a proxy and `ollama_host` at its default:

            fake proxy received: POST http://localhost:11434/api/embeddings HTTP/1.1
            embed() returned   : [0.1, 0.2]

        The text left the machine while `winnow status` said "never transmitted", and the
        vector came back from the proxy rather than from Ollama -- leaked AND wrong, with
        nothing able to tell the difference.

        There is no legitimate reason to proxy 127.0.0.1. An SSH tunnel binds a local port
        directly and involves no proxy, so this does not break the forwarded-host case that
        `judge_location: "cloud"` exists for. A genuinely remote host still honours the
        environment, because a proxy is how many networks reach anything at all -- and the
        privacy statement names it there.
        """
        return is_loopback_host(self.host)

    def _opener(self) -> urllib.request.OpenerDirector:
        if self.bypasses_proxy:
            # An EMPTY ProxyHandler is what disables proxying; omitting the handler lets
            # urllib install the environment's.
            return urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return urllib.request.build_opener()

    def _fetch(self, url: str, data: bytes) -> dict:
        request = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}
        )
        with self._opener().open(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def _post(self, path: str, body: dict) -> dict:
        url = f"{self.host.rstrip('/')}{path}"
        data = json.dumps(body).encode("utf-8")
        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            try:
                return self._fetch(url, data)
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code not in TRANSIENT_STATUS:
                    # Ollama explains itself in the body -- "model 'x' not found" for the
                    # commonest first-run failure of all. Reducing that to a status code
                    # threw away the only sentence that says what to do.
                    raise OllamaError(
                        f"{url} returned HTTP {exc.code}{_detail(exc)}", status=exc.code
                    ) from exc
            except urllib.error.URLError as exc:
                last_error = exc

            if attempt < self.max_retries - 1:
                time.sleep(self.backoff_seconds * (2**attempt))

        raise OllamaError(f"{url} failed after {self.max_retries} attempts: {last_error}")

    # -- generation ------------------------------------------------------------

    def generate(
        self,
        model: str,
        prompt: str,
        *,
        num_ctx: int,
        as_json: bool = False,
        images: list[str] | None = None,
        temperature: float = 0.0,
    ) -> str:
        """Run a prompt.

        `num_ctx` is a required keyword argument with no default, on purpose: see (1) in
        the module docstring. Set it to the model's real context length.

        `as_json` must be False for any prompt that asks for prose -- see (2).
        """
        if not num_ctx or num_ctx <= 0:
            raise ContextWindowNotSet(
                "num_ctx must be a positive integer matching the model's real context "
                "length; Ollama silently truncates to a small default otherwise"
            )

        body: dict = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature, "num_ctx": num_ctx},
        }
        if as_json:
            body["format"] = "json"
        if images:
            body["images"] = images

        return self._post("/api/generate", body).get("response", "")

    def describe_image(
        self, model: str, prompt: str, image_b64: str, *, num_ctx: int
    ) -> str:
        """Describe an image in prose.

        Note there is no `as_json` parameter: forcing JSON on a description prompt is the
        bug this method exists to make unavailable.
        """
        return self.generate(
            model, prompt, num_ctx=num_ctx, as_json=False, images=[image_b64]
        )

    # -- embeddings ------------------------------------------------------------

    def embed(self, model: str, text: str) -> list[float]:
        response = self._post("/api/embeddings", {"model": model, "prompt": text})
        vector = response.get("embedding")
        if not vector:
            # Surface the server's own explanation. It is usually the actionable part --
            # e.g. a server started without embedding support, which no amount of changing
            # the model will fix, and which a generic "no embedding returned" would hide.
            detail = response.get("error")
            raise OllamaError(
                f"model {model!r} returned no embedding: {detail}"
                if detail
                else f"model {model!r} returned no embedding"
            )
        return list(vector)

