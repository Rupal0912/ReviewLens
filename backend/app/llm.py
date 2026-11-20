"""Groq client with exponential backoff. The API key is only ever read server-side."""
import random
import re
import time

import httpx

from . import config


class LLMError(Exception):
    """Non-retryable LLM failure (bad request, auth...)."""


class LLMConfigError(LLMError):
    """No API key configured."""


class TransientLLMError(LLMError):
    """Rate limit / server error / network problem: worth retrying."""

    def __init__(self, msg, retry_after: float | None = None):
        super().__init__(msg)
        self.retry_after = retry_after


def with_backoff(fn, *, max_retries=5, base_delay=1.0, max_delay=30.0,
                 sleep=time.sleep, jitter=True):
    """Call fn(); on TransientLLMError wait base*2**attempt (or Retry-After) and retry."""
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except TransientLLMError as exc:
            if attempt == max_retries:
                raise
            delay = exc.retry_after or min(base_delay * 2 ** attempt, max_delay)
            if jitter:
                delay += random.uniform(0, delay * 0.25)
            sleep(delay)


class GroqClient:
    def __init__(self, api_key=None, model=None, http: httpx.Client | None = None,
                 sleep=time.sleep, base_delay=1.0, jitter=True):
        self.api_key = api_key if api_key is not None else config.GROQ_API_KEY
        self.model = model or config.GROQ_MODEL
        self.http = http or httpx.Client(timeout=60)
        self.sleep = sleep
        self.base_delay = base_delay
        self.jitter = jitter

    def _call(self, messages, json_mode: bool) -> str:
        if not self.api_key:
            raise LLMConfigError("GROQ_API_KEY is not set on the server.")
        body = {"model": self.model, "messages": messages, "temperature": 0}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        try:
            resp = self.http.post(config.GROQ_URL, json=body,
                                  headers={"Authorization": f"Bearer {self.api_key}"})
        except httpx.TransportError as exc:
            raise TransientLLMError(f"network error: {exc}") from exc
        if resp.status_code == 429 or resp.status_code >= 500:
            ra = resp.headers.get("retry-after", "")
            try:
                retry_after = float(ra)
            except ValueError:
                retry_after = None
            raise TransientLLMError(f"HTTP {resp.status_code}", retry_after)
        if resp.status_code >= 400:
            try:
                payload = resp.json()
            except ValueError:
                payload = {}
            error = payload.get("error", {}) if isinstance(payload, dict) else {}
            if isinstance(error, dict):
                details = "; ".join(
                    f"{name}={error[name]}" for name in ("code", "type", "message")
                    if error.get(name) is not None
                )
            else:
                details = ""
            if not details:
                details = "provider returned no structured error details"
            details = details.replace(self.api_key, "[REDACTED]")
            details = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/-]+=*", "Bearer [REDACTED]", details)
            raise LLMError(f"Groq API HTTP {resp.status_code}: {details[:500]}")
        try:
            return resp.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise TransientLLMError("unexpected response shape") from exc

    def complete(self, messages, json_mode=True) -> str:
        return with_backoff(lambda: self._call(messages, json_mode),
                            max_retries=config.MAX_RETRIES, base_delay=self.base_delay,
                            sleep=self.sleep, jitter=self.jitter)
