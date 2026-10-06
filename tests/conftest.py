import json
import shutil
import subprocess
import imageio_ffmpeg
from pathlib import Path

import pytest

from max_channel_agent.config import Settings, read_topic
from max_channel_agent.db import Database
from max_channel_agent.service import Service


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    shutil.copytree(ROOT / "schemas", tmp_path / "schemas")
    shutil.copytree(ROOT / "prompts", tmp_path / "prompts")
    (tmp_path / "config").mkdir()
    app = json.loads((ROOT / "config/app.example.json").read_text(encoding="utf-8-sig"))
    (tmp_path / "config/app.json").write_text(json.dumps(app))
    topic = read_topic(ROOT)
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
    sources = json.loads((ROOT / "config/sources.example.json").read_text(encoding="utf-8-sig"))
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


@pytest.fixture
def clip(project):
    path = project / "fixture.mp4"
    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=160x288:d=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        capture_output=True,
        check=True,
        timeout=30,
    )
    return path
