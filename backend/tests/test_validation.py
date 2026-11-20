import json

import pytest

from app.validation import ValidationFailure, parse_batch, validate_item

OK = {"id": "r1", "sentiment": "positive", "topics": ["price", "price"], "summary": " Good  value ", "needs_reply": False}


def test_valid_item_is_cleaned():
    out = validate_item(OK)
    assert out == {"sentiment": "positive", "topics": ["price"], "summary": "Good value", "needs_reply": False}


@pytest.mark.parametrize("change", [
    {"sentiment": "angry"}, {"topics": []}, {"topics": ["shipping"]}, {"topics": "quality"},
    {"summary": ""}, {"needs_reply": "true"}, {"extra": 1},
])
def test_invalid_items_rejected(change):
    with pytest.raises(ValidationFailure):
        validate_item({**OK, **change})


def test_missing_field_rejected():
    bad = {k: v for k, v in OK.items() if k != "needs_reply"}
    with pytest.raises(ValidationFailure):
        validate_item(bad)


def test_parse_batch_reports_invalid_and_missing_indexes():
    raw = json.dumps({"results": [OK, {**OK, "id": "r2", "sentiment": "???"}]})
    good, bad = parse_batch(raw, 3)
    assert list(good) == [0] and bad == [1, 2]


@pytest.mark.parametrize("raw", ["not json", "[]", '{"results": "x"}', "null", '{"results":[1,"a",null]}'])
def test_malformed_output_never_raises(raw):
    good, bad = parse_batch(raw, 2)
    assert good == {} and bad == [0, 1]
