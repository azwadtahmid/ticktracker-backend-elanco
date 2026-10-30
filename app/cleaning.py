"""Cleaning rules: keep, fix, or reject each raw record (with a reason)."""
import difflib
from datetime import datetime

KNOWN_CITIES = [
    "Birmingham", "Bristol", "Cardiff", "Edinburgh", "Glasgow", "Leeds", "Leicester",
    "Liverpool", "London", "Manchester", "Newcastle", "Nottingham", "Sheffield", "Southampton",
]

# Each species has exactly one Latin name in Elanco's data, so either can fill in the other.
SPECIES_TO_LATIN = {
    "Fox/badger tick": "Ixodes canisuga",
    "Marsh tick": "Ixodes apronophorus",
    "Passerine tick": "Dermacentor frontalis",
    "Southern rodent tick": "Ixodes acuminatus",
    "Tree-hole tick": "Ixodes arboricola",
}
LATIN_TO_SPECIES = {latin: species for species, latin in SPECIES_TO_LATIN.items()}

# Day-first (UK) for ambiguous dates like 01/08/2022.
DATE_FORMATS = ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y %H:%M", "%d/%m/%Y"]

# 0.8 similarity is roughly "1-2 letters off" for city-length words; strict enough that Newport is not Newcastle.
TYPO_CUTOFF = 0.8


def _text(value):
    """Stripped string, or None if missing/blank/not a string."""
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def clean_location(raw):
    """Return (location, corrected). corrected is True only when a typo was fixed."""
    location = _text(raw)
    if location is None:
        return "Unknown", False
    by_lower = {city.lower(): city for city in KNOWN_CITIES}
    if location.lower() in by_lower:
        return by_lower[location.lower()], False
    match = difflib.get_close_matches(location.lower(), by_lower, n=1, cutoff=TYPO_CUTOFF)
    if match:
        return by_lower[match[0]], True
    return location, False  # a real place we don't know (e.g. Bath): keep as sent


def parse_date(raw):
    """Return the date as ISO text, or None if it can't be read."""
    text = _text(raw)
    if text is None:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).isoformat()
        except ValueError:
            pass
    return None


def clean_record(raw):
    """Return (record, reason, location_corrected). Exactly one of record / reason is None."""
    if not isinstance(raw, dict):
        return None, "not a JSON object", False
    record_id = _text(raw.get("id"))
    if record_id is None:
        return None, "missing id", False
    date = parse_date(raw.get("date"))
    if date is None:
        return None, "missing or unreadable date", False

    location, corrected = clean_location(raw.get("location"))
    species = _text(raw.get("species"))
    latin = _text(raw.get("latinName"))
    species = species or LATIN_TO_SPECIES.get(latin, "Unknown")
    latin = latin or SPECIES_TO_LATIN.get(species, "Unknown")

    record = {"id": record_id, "date": date, "location": location, "species": species, "latin_name": latin}
    return record, None, corrected


def clean_all(raw_records):
    """Clean a whole fetch. Duplicate ids are compared after cleaning; the first copy is always kept."""
    kept = {}
    rejected = []
    duplicates = 0
    locations_corrected = 0
    for raw in raw_records:
        record, reason, corrected = clean_record(raw)
        if reason:
            rejected.append((raw, reason))
        elif record["id"] in kept:
            duplicates += 1  # identical or conflicting, the rule is the same: keep the first
        else:
            kept[record["id"]] = record
            locations_corrected += corrected
    return {
        "kept": list(kept.values()),
        "rejected": rejected,
        "duplicates": duplicates,
        "locations_corrected": locations_corrected,
    }
