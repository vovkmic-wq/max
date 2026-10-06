"""Encrypted, integrity-checked portable state; restore only into an empty installation."""

import hashlib
import io
import json
import os
import zipfile

from cryptography.fernet import Fernet, InvalidToken

from .config import AgentError, inside
from .db import Channel, Intent, Job


def backup(service, destination, key):
    with service.db.session() as session:
        if any(not c.paused for c in session.query(Channel).all()):
            raise AgentError("BACKUP_REQUIRES_PAUSE")
        if session.query(Job).filter(Job.state == "leased").first():
            raise AgentError("BACKUP_REQUIRES_STOPPED_WORKER")
    buffer = io.BytesIO()
    files = {
        "database.json": json.dumps(service.db.export(), ensure_ascii=False).encode(),
        "TOPIC.md": (service.settings.root / service.settings.app["topic_path"]).read_bytes(),
        "config/sources.json": (
            service.settings.root / service.settings.app["sources_path"]
        ).read_bytes(),
    }
    media_dir = service.settings.root / service.settings.app["media_dir"]
    if media_dir.exists():
        for path in media_dir.rglob("*"):
            if path.is_file() and not path.is_symlink():
                files["media/" + path.relative_to(media_dir).as_posix()] = path.read_bytes()
    manifest = {
        "schema_version": "1.0",
        "hashes": {name: hashlib.sha256(value).hexdigest() for name, value in files.items()},
    }
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, value in files.items():
            archive.writestr(name, value)
        archive.writestr("manifest.json", json.dumps(manifest))
    try:
        encrypted = Fernet(key).encrypt(buffer.getvalue())
    except (ValueError, TypeError) as exc:
        raise AgentError("BACKUP_KEY_INVALID") from exc
    destination.write_bytes(encrypted)
    if os.name != "nt":
        destination.chmod(0o600)
    return hashlib.sha256(encrypted).hexdigest()


def restore(service, archive_path, key):
    try:
        decrypted = Fernet(key).decrypt(archive_path.read_bytes())
        with zipfile.ZipFile(io.BytesIO(decrypted)) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise AgentError("BACKUP_INVALID")
            manifest = json.loads(archive.read("manifest.json"))
            if manifest.get("schema_version") != "1.0":
                raise AgentError("BACKUP_SCHEMA_MISMATCH")
            if set(names) != set(manifest["hashes"]) | {"manifest.json"}:
                raise AgentError("BACKUP_INVALID")
            content = {}
            for name, expected in manifest["hashes"].items():
                inside(service.settings.root, name)
                value = archive.read(name)
                if hashlib.sha256(value).hexdigest() != expected:
                    raise AgentError("BACKUP_HASH_MISMATCH")
                content[name] = value
            database = json.loads(content["database.json"])
    except (InvalidToken, ValueError, zipfile.BadZipFile, KeyError) as exc:
        raise AgentError("BACKUP_INVALID") from exc
    # Restored settings are validated before any database or configuration mutation.
    from .config import parse_json, validate_schema

    topic_text = content["TOPIC.md"].decode("utf-8-sig")
    import re

    match = re.search(r"```json\s*(.*?)\s*```", topic_text, re.S)
    if not match:
        raise AgentError("BACKUP_TOPIC_INVALID")
    validate_schema(service.settings.root, "topic.schema.json", parse_json(match[1]))
    validate_schema(
        service.settings.root,
        "sources.schema.json",
        parse_json(content["config/sources.json"].decode("utf-8-sig")),
    )
    service.db.restore(database)
    (service.settings.root / service.settings.app["topic_path"]).write_bytes(content["TOPIC.md"])
    (service.settings.root / service.settings.app["sources_path"]).write_bytes(
        content["config/sources.json"]
    )
    for name, value in content.items():
        if name.startswith("media/"):
            path = inside(service.settings.root, service.settings.app["media_dir"] + "/" + name[6:])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(value)
    with service.db.session.begin() as session:
        for channel in session.query(Channel).all():
            channel.paused = True
        for intent in session.query(Intent).filter(Intent.state == "sending"):
            intent.state = "unknown"
        for job in session.query(Job).filter(Job.state == "leased"):
            job.state, job.lease_until, job.owner = "queued", 0, None
    return manifest
