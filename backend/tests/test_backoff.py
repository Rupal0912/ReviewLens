import httpx
import pytest

from app import config
from app.llm import GroqClient, LLMError, TransientLLMError, with_backoff


def test_backoff_delays_double_then_succeed():
    sleeps, attempts = [], {"n": 0}

    def flaky():
        attempts["n"] += 1
        if attempts["n"] < 4:
            raise TransientLLMError("429")
        return "ok"

    assert with_backoff(flaky, base_delay=1, sleep=sleeps.append, jitter=False) == "ok"
    assert sleeps == [1, 2, 4]


def test_backoff_gives_up_after_max_retries():
    sleeps = []

    def always():
        raise TransientLLMError("500")

    with pytest.raises(TransientLLMError):
        with_backoff(always, max_retries=3, sleep=sleeps.append, jitter=False)
    assert len(sleeps) == 3


def test_retry_after_header_is_honoured():
    sleeps, n = [], {"n": 0}

    def once():
        n["n"] += 1
        if n["n"] == 1:
            raise TransientLLMError("429", retry_after=7)
        return "ok"

    with_backoff(once, sleep=sleeps.append, jitter=False)
    assert sleeps == [7]


def _client(handler):
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return GroqClient(api_key="test-key", http=http, sleep=lambda s: None, jitter=False)


def test_groq_client_retries_429_then_succeeds():
    codes = iter([429, 503, 200])

    def handler(request):
        code = next(codes)
        if code != 200:
            return httpx.Response(code)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    assert _client(handler).complete([{"role": "user", "content": "x"}]) == "{}"


def test_groq_client_does_not_retry_auth_errors():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(401, text="bad key")

    with pytest.raises(LLMError):
        _client(handler).complete([{"role": "user", "content": "x"}])
    assert calls["n"] == 1


def test_provider_error_is_visible_and_api_key_is_redacted():
    def handler(request):
        return httpx.Response(404, json={"error": {
            "message": "The model is unavailable; supplied token Bearer test-key",
            "type": "invalid_request_error",
            "code": "model_not_found",
        }})

    with pytest.raises(LLMError) as exc:
        _client(handler).complete([{"role": "user", "content": "x"}])

    message = str(exc.value)
    assert "HTTP 404" in message and "model_not_found" in message
    assert "The model is unavailable" in message
    assert "test-key" not in message
    assert "Bearer [REDACTED]" in message


def test_api_key_goes_only_in_auth_header():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["authorization"]
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    _client(handler).complete([{"role": "user", "content": "x"}])
    assert seen["auth"] == "Bearer test-key" and "test-key" not in seen["body"]
    assert config.GROQ_URL.startswith("https://api.groq.com")
