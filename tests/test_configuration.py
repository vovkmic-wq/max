import json

import pytest

from max_channel_agent.config import AgentError, Settings, inside, parse_json, read_topic

from conftest import write_topic


def test_valid_project(project):
    assert Settings.load(project).channel("main")["enabled"]


@pytest.mark.parametrize("text", ['{"x":1,"x":2}', '{"x":{"y":1,"y":2}}', "{bad"])
def test_reject_malformed_json(text):
    with pytest.raises(AgentError):
        parse_json(text)


@pytest.mark.parametrize(
    "variant",
    [
        "placeholder",
        "timezone",
        "duplicate",
        "mode",
        "language",
        "unknown",
        "negative",
        "commercial",
    ],
)
def test_invalid_topic(project, variant):
    data = read_topic(project)
    channel = data["channels"][0]
    match variant:
        case "placeholder":
            channel["theme"] = "ЗАПОЛНИТЬ"
        case "timezone":
            channel["publication"]["timezone"] = "Planet/Mars"
        case "duplicate":
            data["channels"].append(channel.copy())
        case "mode":
            channel["publication"]["mode"] = "unlimited"
        case "language":
            channel["output_language"] = "en"
        case "unknown":
            channel["secret"] = "value"
        case "negative":
            channel["budget"]["daily_llm_limit"] = -1
        case "commercial":
            channel["monetization"]["enabled"] = True
    write_topic(project, data)
    with pytest.raises(AgentError):
        read_topic(project)


@pytest.mark.parametrize("path", ["../outside", "config/../../outside"])
def test_paths_stay_inside(project, path):
    with pytest.raises(AgentError):
        inside(project, path)


@pytest.mark.parametrize(
    "variant", ["unknown_channel", "duplicate_id", "unverified", "file_url", "too_fast"]
)
def test_sources_invalid(project, variant):
    path = project / "config/sources.json"
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    source = data["sources"][0]
    match variant:
        case "unknown_channel":
            source["channel_ids"] = ["missing"]
        case "duplicate_id":
            data["sources"].append(source.copy())
        case "unverified":
            source["rights"]["verified"] = False
        case "file_url":
            source["endpoint"] = "file:///secret"
        case "too_fast":
            source["interval_seconds"] = 1
    path.write_text(json.dumps(data))
    with pytest.raises(AgentError):
        Settings.load(project)
