"""Deterministic editorial gates around model output."""

import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from .collectors import detect_language
from .config import AgentError


def numbers(text):
    return set(re.findall(r"\d+(?:[.,]\d+)*", text))


def translation_gate(original, translated):
    if numbers(original) != numbers(translated):
        raise AgentError("TRANSLATION_NUMBER_CHANGED")
    if detect_language(translated) != "ru":
        raise AgentError("TRANSLATION_NOT_RUSSIAN")
    # Negation and semantic alignment require editorial review in addition to this numerical gate.


def validate_draft(value, materials, channel, model_verified=False, allow_original=False):
    required = {
        "title",
        "body",
        "language",
        "source_ids",
        "decision",
        "reason_codes",
        "claims",
        "confidence",
        "payload",
    }
    if set(value) != required:
        raise AgentError("EDITOR_RESULT_FIELDS_INVALID")
    if not isinstance(value["body"], str) or not value["body"].strip():
        raise AgentError("EDITOR_EMPTY_BODY")
    if not isinstance(value["title"], str) or not isinstance(value["confidence"], (float, int)):
        raise AgentError("EDITOR_RESULT_TYPES_INVALID")
    if not 0 <= value["confidence"] <= 1 or value["decision"] not in {"accept", "review", "reject"}:
        raise AgentError("EDITOR_RESULT_TYPES_INVALID")
    if not isinstance(value["claims"], list) or not isinstance(value["reason_codes"], list):
        raise AgentError("EDITOR_RESULT_TYPES_INVALID")
    ids = {m["id"]: m for m in materials}
    if (
        not isinstance(value["source_ids"], list)
        or (not value["source_ids"] and not allow_original)
        or not set(value["source_ids"]) <= set(ids)
    ):
        raise AgentError("EDITOR_UNKNOWN_SOURCE")
    body = value["body"]
    reasons = []
    if value["language"] != "ru" or detect_language(body) != "ru":
        reasons.append("OUTPUT_NOT_RUSSIAN")
    if len(body) > min(4000, channel["publication"]["max_chars"]):
        reasons.append("LENGTH_EXCEEDED")
    if any(term.casefold() in body.casefold() for term in channel["exclude_topics"]):
        reasons.append("EXCLUDED_TOPIC")
    texts = " ".join(m["text"] + " " + m["title"] for m in materials)
    if not allow_original and not numbers(body) <= numbers(
        texts + " ".join(m["url"] for m in materials)
    ):
        reasons.append("UNSUPPORTED_NUMBER")
    for mid in value["source_ids"]:
        if not ids[mid]["url"] or ids[mid]["url"] not in body:
            reasons.append("MISSING_SOURCE_LINK")
    for claim in value["claims"]:
        if not isinstance(claim, dict) or set(claim) != {"text", "material_id", "quote"}:
            raise AgentError("CLAIM_SCHEMA_INVALID")
        mid, quote = claim["material_id"], claim["quote"]
        if mid not in ids or not quote or quote not in ids[mid]["text"]:
            reasons.append("INSUFFICIENT_EVIDENCE")
        if claim["text"] not in body:
            reasons.append("CLAIM_NOT_IN_BODY")
    if not value["claims"] or not model_verified:
        reasons.append("EDITOR_REVIEW_REQUIRED")
    return sorted(set(reasons))


def next_slot(channel, occupied, earliest=None):
    policy = channel["publication"]
    zone = ZoneInfo(policy["timezone"])
    start = datetime.fromtimestamp(earliest, UTC) if earliest else datetime.now(UTC)
    local = start.astimezone(zone)
    for offset in range(31):
        day = local.date() + timedelta(days=offset)
        count = sum(datetime.fromtimestamp(t, UTC).astimezone(zone).date() == day for t in occupied)
        if count >= policy["max_posts_per_day"]:
            continue
        for slot in sorted(policy["slots"]):
            hour, minute = map(int, slot.split(":"))
            candidate = datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone)
            # Reject nonexistent local times (DST gaps). Choose fold=0 for ambiguous times.
            if candidate.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != candidate.replace(
                tzinfo=None
            ):
                continue
            stamp = candidate.timestamp()
            if stamp < start.timestamp():
                continue
            if all(abs(stamp - t) >= policy["min_gap_minutes"] * 60 for t in occupied):
                return stamp
    raise AgentError("NO_CALENDAR_SLOT")
