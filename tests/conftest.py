import json
import shutil
from pathlib import Path

import pytest

from max_channel_agent.config import Settings
from max_channel_agent.db import Database
from max_channel_agent.service import Service


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    shutil.copytree(ROOT / "schemas", tmp_path / "schemas")
    shutil.copytree(ROOT / "prompts", tmp_path / "prompts")
    (tmp_path / "config").mkdir()
    app = json.loads((ROOT / "config/app.example.json").read_text())
    (tmp_path / "config/app.json").write_text(json.dumps(app))
    topic = Settings.load(ROOT).topic
    topic["channels"][0].update(
        {
            "enabled": True,
            "name": "Нейровидео",
            "theme": "Короткие видео нейросетей",
            "audience": "Любители нейровидео",
            "include_topics": ["видео"],
            "exclude_topics": ["казино"],
            "geography": ["весь мир"],
        }
    )
    write_topic(tmp_path, topic)
    sources = json.loads((ROOT / "config/sources.example.json").read_text())
    source = sources["sources"][0]
    source["enabled"] = True
    source["rights"].update(
        {
            "verified": True,
            "allow_storage": True,
            "allow_derivative": True,
            "evidence_ref": "test_permission",
        }
    )
    (tmp_path / "config/sources.json").write_text(json.dumps(sources), encoding="utf-8")
    return tmp_path


def write_topic(root, topic):
    (root / "TOPIC.md").write_text(
        "<!-- TOPIC_CONFIG_BEGIN -->\n```json\n"
        + json.dumps(topic, ensure_ascii=False)
        + "\n```\n<!-- TOPIC_CONFIG_END -->",
        encoding="utf-8",
    )


@pytest.fixture
def service(project):
    settings = Settings.load(project)
    db = Database(settings)
    db.initialize()
    service = Service(settings, db)
    service.activate()
    yield service
    service.close()
