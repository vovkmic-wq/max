"""Versioned configuration. External text can never change these permissions."""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jsonschema import Draft202012Validator, FormatChecker


class AgentError(Exception):
    def __init__(self, code: str, status: int = 422):
        self.code, self.status = code, status
        super().__init__(code)


def unique_keys(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise AgentError("DUPLICATE_JSON_KEY")
        value[key] = item
    return value


def parse_json(text: str):
    try:
        return json.loads(text, object_pairs_hook=unique_keys)
    except (json.JSONDecodeError, ValueError) as exc:
        raise AgentError("INVALID_JSON") from exc


def fingerprint(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def inside(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise AgentError("PATH_OUTSIDE_PROJECT")
    return candidate


def validate_schema(root: Path, name: str, value):
    schema = parse_json((root / "schemas" / name).read_text(encoding="utf-8-sig"))
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value))
    if errors:
        # Validation messages may contain user-controlled secret values.
        raise AgentError("CONFIG_SCHEMA_INVALID")


def read_topic(root: Path, path="TOPIC.md"):
    text = inside(root, path).read_text(encoding="utf-8-sig")
    pattern = r"<!-- TOPIC_CONFIG_BEGIN -->\s*```json\s*(.*?)\s*```\s*<!-- TOPIC_CONFIG_END -->"
    matches = re.findall(pattern, text, re.S)
    if len(matches) != 1 or text.count("<!-- TOPIC_CONFIG_BEGIN -->") != 1:
        raise AgentError("TOPIC_BLOCK_INVALID")
    topic = parse_json(matches[0])
    validate_schema(root, "topic.schema.json", topic)
    ids = [c["id"] for c in topic["channels"]]
    if len(ids) != len(set(ids)):
        raise AgentError("DUPLICATE_CHANNEL_ID")
    for channel in topic["channels"]:
        try:
            ZoneInfo(channel["publication"]["timezone"])
        except ZoneInfoNotFoundError as exc:
            raise AgentError("INVALID_TIMEZONE") from exc
        if channel["enabled"] and "ЗАПОЛНИТЬ" in json.dumps(channel, ensure_ascii=False):
            raise AgentError("TOPIC_NOT_FILLED")
        if channel["monetization"]["enabled"] and not channel["monetization"]["models"]:
            raise AgentError("MONETIZATION_MODEL_REQUIRED")
    return topic


def read_sources(root, path, topic):
    data = parse_json(inside(root, path).read_text(encoding="utf-8-sig"))
    validate_schema(root, "sources.schema.json", data)
    ids = [s["id"] for s in data["sources"]]
    if len(ids) != len(set(ids)):
        raise AgentError("DUPLICATE_SOURCE_ID")
    channel_ids = {c["id"] for c in topic["channels"]}
    for source in data["sources"]:
        if not set(source["channel_ids"]) <= channel_ids:
            raise AgentError("UNKNOWN_CHANNEL")
        if source["enabled"] and source.get("endpoint"):
            from .network import validate_url

            validate_url(source["endpoint"], resolve=False)
    return data


@dataclass
class Settings:
    root: Path
    app: dict
    topic: dict
    sources: dict

    @classmethod
    def load(cls, root: Path, app_path="config/app.json"):
        root = root.resolve()
        app = parse_json(inside(root, app_path).read_text(encoding="utf-8-sig"))
        if app.get("schema_version") != "1.0":
            raise AgentError("APP_VERSION_INVALID")
        for key in ("state_dir", "media_dir", "logs_dir", "topic_path", "sources_path"):
            inside(root, app[key])
        for section in ("opencode", "max"):
            if app[section]["adapter_mode"] not in {"fake", "live"}:
                raise AgentError("ADAPTER_MODE_INVALID")
        if app["collection"]["deny_private_networks"] is not True:
            raise AgentError("PRIVATE_NETWORKS_MUST_BE_DENIED")
        topic = read_topic(root, app["topic_path"])
        sources = read_sources(root, app["sources_path"], topic)
        return cls(root, app, topic, sources)

    @property
    def hash(self):
        return fingerprint({"topic": self.topic, "sources": self.sources})

    def channel(self, channel_id):
        for channel in self.topic["channels"]:
            if channel["id"] == channel_id:
                return channel
        raise AgentError("UNKNOWN_CHANNEL", 404)

    def source(self, source_id):
        for source in self.sources["sources"]:
            if source["id"] == source_id:
                return source
        raise AgentError("UNKNOWN_SOURCE", 404)
