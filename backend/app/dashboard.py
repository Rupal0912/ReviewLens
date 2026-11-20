"""Turns stored reviews into the numbers the dashboard shows."""
from collections import Counter

EXPECTED = {1: "negative", 2: "negative", 3: "neutral", 4: "positive", 5: "positive"}


def rating_mismatch(rating, sentiment) -> bool | None:
    """True when stars and text clearly contradict (4-5 stars + negative, 1-2 stars + positive)."""
    if rating is None or sentiment is None:
        return None
    return (rating >= 4 and sentiment == "negative") or (rating <= 2 and sentiment == "positive")


def _top(reviews, sentiment, n=3):
    """Top topics among reviews of one sentiment ('other' only fills empty slots)."""
    counts: Counter = Counter()
    example: dict = {}
    for r in reviews:
        if r["sentiment"] != sentiment:
            continue
        for t in r["topics"]:
            counts[t] += 1
            example.setdefault(t, r["summary"])
    ranked = sorted(counts.items(), key=lambda kv: (kv[0] == "other", -kv[1], kv[0]))[:n]
    return [{"topic": t, "count": c, "example": example[t]} for t, c in ranked]


def build_dashboard(upload: dict, reviews: list[dict]) -> dict:
    analysed = [r for r in reviews if r["status"] == "analyzed"]
    sentiments = Counter(r["sentiment"] for r in analysed)
    total = len(analysed)
    pct = {s: (round(100 * sentiments[s] / total, 1) if total else 0.0)
           for s in ("positive", "neutral", "negative")}

    for r in reviews:
        r["mismatch"] = rating_mismatch(r["rating"], r["sentiment"]) if r["status"] == "analyzed" else None

    rated = [r for r in analysed if r["rating"] is not None]
    agree = sum(1 for r in rated if EXPECTED[r["rating"]] == r["sentiment"])
    topic_counts = Counter(t for r in analysed for t in r["topics"])

    return {
        "upload": {"id": upload["id"], "filename": upload["filename"], "created_at": upload["created_at"]},
        "stats": {
            "total_rows": len(reviews),
            "analysed": total,
            "skipped": sum(1 for r in reviews if r["status"] == "skipped_empty"),
            "failed": sum(1 for r in reviews if r["status"] == "analysis_failed"),
            "duplicates": sum(1 for r in reviews if r["duplicate_of"]),
            "sentiment": {s: sentiments[s] for s in ("positive", "neutral", "negative")},
            "percentages": pct,
            "needs_reply": sum(1 for r in analysed if r["needs_reply"]),
            "mismatches": sum(1 for r in analysed if r["mismatch"]),
            "agreement_pct": round(100 * agree / len(rated), 1) if rated else None,
            "topics": [{"topic": t, "count": c} for t, c in topic_counts.most_common()],
            "top_complaints": _top(analysed, "negative"),
            "top_praises": _top(analysed, "positive"),
            "run": upload["run_stats"],
        },
        "reviews": reviews,
        "products": sorted({r["product"] for r in reviews if r["product"]}),
    }
