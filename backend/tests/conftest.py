import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.db import Database  # noqa: E402
from app.validation import ValidationFailure  # noqa: E402,F401

GOOD = {"sentiment": "negative", "topics": ["quality"], "summary": "Item arrived broken.", "needs_reply": True}


class FakeLLM:
    """Stands in for Groq. `handler(texts, call_no)` returns the raw string to send back."""
    model = "fake-model"

    def __init__(self, handler=None):
        self.handler = handler or self.default
        self.calls = []

    @staticmethod
    def default(texts, call_no):
        return json.dumps({"results": [{"id": f"r{i + 1}", **GOOD} for i in range(len(texts))]})

    def complete(self, messages, json_mode=True):
        self.calls.append(messages)
        if not json_mode:
            return "Thanks for your feedback, we are sorry about the issue."
        payload = json.loads(messages[1]["content"].split("\n", 1)[1].split("\nYour previous")[0])
        return self.handler([p["review_text"] for p in payload], len(self.calls))


@pytest.fixture
def db(tmp_path):
    return Database(str(tmp_path / "test.db"))


@pytest.fixture
def fake_llm():
    return FakeLLM()
