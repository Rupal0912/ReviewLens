"""CSV parsing, cleaning and duplicate detection. No LLM or DB code here."""
import csv
import hashlib
import io
import math
from dataclasses import dataclass, field

# Accepted header names (lower-cased) for each logical column.
COLUMN_ALIASES = {
    "review_id": ("review_id", "id", "reviewid"),
    "product": ("product", "product_name", "product_id", "item"),
    "rating": ("rating", "stars", "score"),
    "text": ("review_text", "review", "text", "comment", "body", "content"),
}


class CSVError(ValueError):
    """The file cannot be used at all (not a CSV, no review column...)."""


@dataclass
class CleanReview:
    row_number: int
    review_id: str
    product: str
    text: str
    rating_raw: str
    rating: int | None
    text_hash: str | None
    status: str                       # "valid" | "empty"
    duplicate_of: str | None = None
    issues: list[str] = field(default_factory=list)


def normalize_text(text: str) -> str:
    return " ".join(text.split()).lower()


def hash_text(text: str) -> str:
    """Hash of whitespace/case-normalised text: same review => same hash."""
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def parse_rating(raw) -> int | None:
    """Return an int 1-5, or None for missing / invalid ('five', 7, 3.5 ...)."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        value = float(s)
    except ValueError:
        return None
    if not math.isfinite(value) or not value.is_integer() or not 1 <= value <= 5:
        return None
    return int(value)


def _find_columns(fieldnames):
    lowered = {(name or "").strip().lower(): name for name in fieldnames}
    found = {}
    for logical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in lowered:
                found[logical] = lowered[alias]
                break
    if "text" not in found:
        raise CSVError(
            "No review text column found. Expected one of: "
            + ", ".join(COLUMN_ALIASES["text"])
        )
    return found


def clean_csv(content: bytes | str) -> list[CleanReview]:
    if isinstance(content, bytes):
        try:
            content = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise CSVError("File is not valid UTF-8 text.") from exc
    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames:
        raise CSVError("The CSV file is empty.")
    cols = _find_columns(reader.fieldnames)

    reviews: list[CleanReview] = []
    first_seen: dict[str, str] = {}
    first_id_seen: set[str] = set()
    for n, row in enumerate(reader, start=1):
        def get(key):
            return (row.get(cols[key]) or "").strip() if key in cols else ""

        review_id = get("review_id") or f"ROW{n:03d}"
        text = get("text")
        rating_raw = get("rating")
        rating = parse_rating(rating_raw)
        issues: list[str] = []
        if review_id in first_id_seen:
            issues.append("duplicate_review_id")
        else:
            first_id_seen.add(review_id)
        if not rating_raw:
            issues.append("missing_rating")
        elif rating is None:
            issues.append("invalid_rating")

        if not text:
            issues.append("empty_text")
            reviews.append(CleanReview(n, review_id, get("product") or "Unknown",
                                       "", rating_raw, rating, None, "empty", None, issues))
            continue

        h = hash_text(text)
        dup_of = first_seen.get(h)
        if dup_of:
            issues.append("duplicate")
        else:
            first_seen[h] = review_id
        reviews.append(CleanReview(n, review_id, get("product") or "Unknown",
                                   text, rating_raw, rating, h, "valid", dup_of, issues))
    return reviews
