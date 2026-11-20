from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from conftest import FakeLLM

SAMPLE = (Path(__file__).resolve().parents[2] / "sample_data" / "reviews_sample.csv").read_bytes()


@pytest.fixture
def client(db):
    app.state.db, app.state.llm = db, FakeLLM()
    yield TestClient(app)
    app.state.db = app.state.llm = None


def test_upload_dashboard_and_reply(client):
    r = client.post("/api/upload", files={"file": ("reviews.csv", SAMPLE, "text/csv")})
    assert r.status_code == 200
    data = r.json()
    s = data["stats"]
    assert s["total_rows"] == 30 and s["analysed"] == 29 and s["skipped"] == 1
    assert sum(s["percentages"].values()) == pytest.approx(100, abs=0.2)
    assert len(s["top_complaints"]) >= 1
    target = next(x for x in data["reviews"] if x["needs_reply"])
    reply = client.post(f"/api/reviews/{target['id']}/reply").json()
    assert reply["suggested_reply"] and reply["cached"] is False
    assert client.post(f"/api/reviews/{target['id']}/reply").json()["cached"] is True


def test_rejects_non_csv_and_bad_csv(client):
    assert client.post("/api/upload", files={"file": ("a.txt", b"x", "text/plain")}).status_code == 400
    assert client.post("/api/upload", files={"file": ("a.csv", b"a,b\n1,2\n", "text/csv")}).status_code == 400


def test_missing_api_key_returns_503(db):
    from app.llm import GroqClient
    app.state.db, app.state.llm = db, GroqClient(api_key="")
    c = TestClient(app)
    r = c.post("/api/upload", files={"file": ("r.csv", SAMPLE, "text/csv")})
    assert r.status_code == 503
    app.state.db = app.state.llm = None


def test_reply_refused_when_not_needed(db):
    import json
    from conftest import GOOD
    quiet = {**GOOD, "sentiment": "positive", "needs_reply": False}
    app.state.db = db
    app.state.llm = FakeLLM(lambda t, n: json.dumps({"results": [{"id": "r1", **quiet}]}))
    c = TestClient(app)
    data = c.post("/api/upload", files={"file": ("r.csv", b"review_id,product,rating,review_text\nA,P,5,great\n", "text/csv")}).json()
    assert c.post(f"/api/reviews/{data['reviews'][0]['id']}/reply").status_code == 400
    assert c.post("/api/reviews/9999/reply").status_code == 404
    app.state.db = app.state.llm = None
