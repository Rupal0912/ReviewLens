from pathlib import Path

import pytest

from app.cleaning import CSVError, clean_csv, hash_text, parse_rating

SAMPLE = Path(__file__).resolve().parents[2] / "sample_data" / "reviews_sample.csv"


def by_id(rows):
    return {r.review_id: r for r in rows}


def test_edge_cases_in_sample_file():
    rows = by_id(clean_csv(SAMPLE.read_bytes()))
    assert len(rows) == 30
    assert rows["R005"].status == "empty" and "empty_text" in rows["R005"].issues
    assert rows["R010"].rating is None and "missing_rating" in rows["R010"].issues
    assert rows["R022"].rating is None and "invalid_rating" in rows["R022"].issues
    assert rows["R009"].status == "valid"            # emoji-only still goes to the LLM


def test_duplicate_detection_keeps_both_rows():
    rows = by_id(clean_csv(SAMPLE.read_bytes()))
    assert rows["R012"].duplicate_of is None
    assert rows["R015"].duplicate_of == "R012"
    assert rows["R012"].text_hash == rows["R015"].text_hash


def test_hash_ignores_case_and_whitespace():
    assert hash_text("Great  product ") == hash_text("great product")


@pytest.mark.parametrize("raw,expected", [("5", 5), ("3.0", 3), ("five", None), ("", None),
                                          ("0", None), ("6", None), ("3.5", None), (None, None),
                                          ("NaN", None), ("Infinity", None), ("-Infinity", None),
                                          ("not-a-rating", None), ("1e10000", None)])
def test_parse_rating(raw, expected):
    assert parse_rating(raw) == expected


@pytest.mark.parametrize("raw", ["NaN", "Infinity", "-Infinity", "not-a-rating", "0", "6", "3.5"])
def test_invalid_rating_is_flagged_without_crashing_ingestion(raw):
    csv = f'review_id,product,rating,review_text\nA,Mug,{raw},Nice mug\n'

    row = clean_csv(csv)[0]

    assert row.rating is None
    assert "invalid_rating" in row.issues
    assert "missing_rating" not in row.issues


def test_missing_rating_is_flagged_and_empty_review_stays_skipped():
    rows = clean_csv('review_id,product,rating,review_text\nA,Mug,,Nice mug\nB,Mug,,\n')

    assert "missing_rating" in rows[0].issues
    assert "invalid_rating" not in rows[0].issues
    assert rows[1].status == "empty"
    assert "missing_rating" in rows[1].issues
    assert "empty_text" in rows[1].issues


def test_duplicate_review_ids_are_flagged_without_changing_text_duplicate_detection():
    rows = clean_csv(
        'review_id,product,rating,review_text\n'
        'A,Mug,5,First text\n'
        'A,Mug,4,Second text\n'
        'A,Mug,3,First text\n'
    )

    assert "duplicate_review_id" not in rows[0].issues
    assert "duplicate_review_id" in rows[1].issues
    assert rows[1].duplicate_of is None
    assert "duplicate_review_id" in rows[2].issues
    assert rows[2].duplicate_of == "A"
    assert "duplicate" in rows[2].issues


def test_missing_text_column_raises():
    with pytest.raises(CSVError):
        clean_csv("a,b\n1,2\n")


def test_alternative_column_names():
    rows = clean_csv("id,product_name,stars,review\nX1,Mug,4,Nice mug\n")
    assert rows[0].review_id == "X1" and rows[0].rating == 4 and rows[0].product == "Mug"
