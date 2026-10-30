import json

import pytest

from app.cleaning import clean_all, clean_location, clean_record, parse_date


def raw(**overrides):
    record = {
        "id": "abc123",
        "date": "2023-06-01T10:00:00",
        "location": "Leeds",
        "species": "Marsh tick",
        "latinName": "Ixodes apronophorus",
    }
    record.update(overrides)
    return record


@pytest.mark.parametrize("value, expected", [
    ("London", ("London", False)),
    (" london ", ("London", False)),
    ("LONDON", ("London", False)),
    ("Londn", ("London", True)),
    ("Leicster", ("Leicester", True)),
    ("Leeds", ("Leeds", False)),
    ("Newport", ("Newport", False)),
    ("Bath", ("Bath", False)),
    (None, ("Unknown", False)),
    ("   ", ("Unknown", False)),
])
def test_clean_location(value, expected):
    assert clean_location(value) == expected


@pytest.mark.parametrize("value, expected", [
    ("2022-08-01T06:40:31", "2022-08-01T06:40:31"),
    ("2022-08-01 06:40:31", "2022-08-01T06:40:31"),
    ("01/08/2022", "2022-08-01T00:00:00"),
    ("not a date", None),
    ("", None),
    (None, None),
    (12345, None),
])
def test_parse_date(value, expected):
    assert parse_date(value) == expected


def test_clean_record_keeps_good_record():
    record, reason, corrected = clean_record(raw())
    assert reason is None and corrected is False
    assert record == {"id": "abc123", "date": "2023-06-01T10:00:00", "location": "Leeds",
                      "species": "Marsh tick", "latin_name": "Ixodes apronophorus"}


@pytest.mark.parametrize("bad, reason", [
    (raw(id=None), "missing id"),
    (raw(id=""), "missing id"),
    (raw(date=None), "missing or unreadable date"),
    (raw(date="yesterday"), "missing or unreadable date"),
    ("just a string", "not a JSON object"),
])
def test_clean_record_rejects_with_reason(bad, reason):
    record, got_reason, _ = clean_record(bad)
    assert record is None and got_reason == reason


def test_missing_key_entirely_is_rejected():
    r = raw()
    del r["date"]
    assert clean_record(r)[1] == "missing or unreadable date"


def test_missing_location_becomes_unknown():
    record, _, _ = clean_record(raw(location=None))
    assert record["location"] == "Unknown"


def test_species_and_latin_name_fill_each_other():
    assert clean_record(raw(species=None))[0]["species"] == "Marsh tick"
    assert clean_record(raw(latinName=None))[0]["latin_name"] == "Ixodes apronophorus"
    both_missing = clean_record(raw(species=None, latinName=None))[0]
    assert both_missing["species"] == "Unknown" and both_missing["latin_name"] == "Unknown"


def test_duplicate_identical_after_cleaning_kept_once():
    result = clean_all([raw(location="Leeds"), raw(location="Leeds ")])
    assert len(result["kept"]) == 1 and result["duplicates"] == 1


def test_duplicate_conflicting_keeps_first():
    result = clean_all([raw(location="Leeds"), raw(location="Bristol")])
    assert [r["location"] for r in result["kept"]] == ["Leeds"]
    assert result["duplicates"] == 1


def test_clean_all_counts_rejections_and_corrections():
    result = clean_all([raw(id="a"), raw(id="b", location="Londn"), raw(id="c", date=None)])
    assert [r["id"] for r in result["kept"]] == ["a", "b"]
    assert result["rejected"] == [(raw(id="c", date=None), "missing or unreadable date")]
    assert result["locations_corrected"] == 1


def test_real_snapshot_is_clean():
    with open("data/seed.json", encoding="utf-8") as f:
        records = json.load(f)
    result = clean_all(records)
    assert len(result["kept"]) == 1000
    assert result["rejected"] == [] and result["duplicates"] == 0 and result["locations_corrected"] == 0
