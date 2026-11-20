"""Strict schema validation for LLM output. Nothing from the model is trusted."""
import json

SENTIMENTS = {"positive", "neutral", "negative"}
TOPICS = {"quality", "delivery", "price", "packaging", "support", "size_fit", "other"}
FIELDS = {"sentiment", "topics", "summary", "needs_reply"}


class ValidationFailure(ValueError):
    pass


def validate_item(obj) -> dict:
    """Return a clean {sentiment, topics, summary, needs_reply} or raise ValidationFailure."""
    if not isinstance(obj, dict):
        raise ValidationFailure("item is not an object")
    missing = FIELDS - set(obj)
    extra = set(obj) - FIELDS - {"id"}
    if missing:
        raise ValidationFailure(f"missing fields: {sorted(missing)}")
    if extra:
        raise ValidationFailure(f"unexpected fields: {sorted(extra)}")
    if obj["sentiment"] not in SENTIMENTS:
        raise ValidationFailure(f"bad sentiment: {obj['sentiment']!r}")
    topics = obj["topics"]
    if not isinstance(topics, list) or not topics or not all(t in TOPICS for t in topics):
        raise ValidationFailure(f"bad topics: {topics!r}")
    summary = obj["summary"]
    if not isinstance(summary, str) or not summary.strip():
        raise ValidationFailure("empty summary")
    if not isinstance(obj["needs_reply"], bool):
        raise ValidationFailure("needs_reply must be a boolean")
    return {
        "sentiment": obj["sentiment"],
        "topics": list(dict.fromkeys(topics)),
        "summary": " ".join(summary.split())[:300],
        "needs_reply": obj["needs_reply"],
    }


def parse_batch(raw: str, count: int) -> tuple[dict[int, dict], list[int]]:
    """Parse a batch response for `count` reviews (ids r1..rN).
    Returns ({index: valid_result}, [indexes missing or invalid]). Never raises."""
    results: dict[int, dict] = {}
    try:
        data = json.loads(raw)
        items = data.get("results") if isinstance(data, dict) else data
        if not isinstance(items, list):
            return {}, list(range(count))
    except (json.JSONDecodeError, TypeError):
        return {}, list(range(count))
    for item in items:
        try:
            rid = item.get("id") if isinstance(item, dict) else None
            idx = int(str(rid).lstrip("r")) - 1
            if not 0 <= idx < count or idx in results:
                continue
            results[idx] = validate_item(item)
        except (ValidationFailure, ValueError, TypeError):
            continue
    return results, [i for i in range(count) if i not in results]
