"""Upload pipeline: clean -> cache lookup -> batched LLM analysis -> validate/retry -> store."""
import logging
import time

from . import config
from .cleaning import clean_csv
from .db import Database
from .llm import LLMConfigError, LLMError
from .prompts import ANALYSIS_PROMPT_VERSION, build_analysis_messages, build_reply_messages
from .validation import parse_batch

logger = logging.getLogger(__name__)


def _run_batch(llm, texts: list[str], reminder: bool = False):
    raw = llm.complete(build_analysis_messages(texts, reminder), json_mode=True)
    return parse_batch(raw, len(texts))


def analyze_texts(llm, items: list[tuple[str, str]], batch_size: int, counters: dict) -> dict[str, dict]:
    """items = [(text_hash, text)]. Batches are sent one after another (never in parallel).
    Invalid items are retried once; anything still invalid is simply absent from the result
    (the caller marks it analysis_failed). Returns {text_hash: validated_result}."""
    out: dict[str, dict] = {}
    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        try:
            counters["ai_calls"] += 1
            ok, bad = _run_batch(llm, [t for _, t in batch])
            for idx, res in ok.items():
                out[batch[idx][0]] = res
            if bad:                                   # retry invalid items exactly once
                retry = [batch[j] for j in bad]
                counters["ai_calls"] += 1
                counters["validation_retries"] += len(retry)
                ok2, _ = _run_batch(llm, [t for _, t in retry], reminder=True)
                for idx, res in ok2.items():
                    out[retry[idx][0]] = res
        except LLMConfigError:
            raise
        except LLMError as exc:
            counters["api_failures"] += 1             # backoff exhausted: leave batch failed
            logger.error("LLM analysis batch failed (model=%s, batch_size=%d): %s",
                         getattr(llm, "model", "unknown"), len(batch), exc)
    return out


def process_upload(db: Database, llm, filename: str, content: bytes,
                   batch_size: int | None = None, model: str | None = None) -> int:
    started = time.perf_counter()
    batch_size = batch_size or config.BATCH_SIZE
    model = model or getattr(llm, "model", "unknown")
    reviews = clean_csv(content)                      # raises CSVError for unusable files

    valid = [r for r in reviews if r.status == "valid"]
    unique: dict[str, str] = {}
    for r in valid:
        unique.setdefault(r.text_hash, r.text)

    cached = db.get_analyses(list(unique), model, ANALYSIS_PROMPT_VERSION)
    to_analyze = [(h, t) for h, t in unique.items() if h not in cached]
    counters = {"ai_calls": 0, "validation_retries": 0, "api_failures": 0}
    fresh = analyze_texts(llm, to_analyze, batch_size, counters) if to_analyze else {}
    for h, res in fresh.items():
        db.save_analysis(h, res, model, ANALYSIS_PROMPT_VERSION)  # only completed analyses are cached
    results = {**cached, **fresh}

    upload_id = db.create_upload(filename)
    for r in reviews:
        if r.status == "empty":
            status = "skipped_empty"
        elif r.text_hash in results:
            status = "analyzed"
        else:
            status = "analysis_failed"
        db.add_review(upload_id, r, status,
                      model if status == "analyzed" else None,
                      ANALYSIS_PROMPT_VERSION if status == "analyzed" else None)

    db.set_run_stats(upload_id, {
        "ai_calls": counters["ai_calls"],
        "validation_retries": counters["validation_retries"],
        "api_failures": counters["api_failures"],
        "cache_hits": len(cached),                    # unique texts answered from SQLite
        "duplicates_reused": sum(1 for r in valid if r.duplicate_of),
        "seconds": round(time.perf_counter() - started, 2),
    })
    return upload_id


def generate_reply(llm, review: dict) -> str:
    raw = llm.complete(build_reply_messages(review["text"], review["product"], review["summary"]),
                       json_mode=False)
    reply = " ".join(raw.split())[:600]
    if not reply:
        raise LLMError("empty reply")
    return reply
