"""Owned short-video assets. Generation backends are explicit, never simulated as AI output."""

import hashlib
import re
import shutil
import subprocess

import httpx

from .config import AgentError, inside
from .db import now


def inspect_video(root, relative_path, duration_limit=60, max_bytes=104857600):
    path = inside(root, relative_path)
    if path.suffix.lower() != ".mp4" or not path.is_file():
        raise AgentError("VIDEO_MP4_REQUIRED")
    if path.stat().st_size > max_bytes:
        raise AgentError("VIDEO_TOO_LARGE")
    import imageio_ffmpeg

    try:
        # Fixed executable and argument array; no shell interpolation.
        result = subprocess.run(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-i", str(path)],
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AgentError("VIDEO_INSPECTION_FAILED") from exc
    output = result.stderr.decode("utf-8", errors="replace")
    duration_match = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", output)
    if not duration_match or "Video:" not in output:
        raise AgentError("VIDEO_STREAM_INVALID")
    hours, minutes, seconds = map(float, duration_match.groups())
    duration = hours * 3600 + minutes * 60 + seconds
    if not 0 < duration <= duration_limit:
        raise AgentError("VIDEO_DURATION_EXCEEDED")
    return {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "duration_seconds": duration,
        "bytes": path.stat().st_size,
        "format": "mp4",
    }


def attach_video(service, draft_id, relative_path, rights_basis, actor="owner"):
    from sqlalchemy import select, update
    from .config import fingerprint
    from .db import Approval, Draft, DraftRevision, Intent

    if not isinstance(rights_basis, str) or len(rights_basis.strip()) < 10:
        raise AgentError("VIDEO_RIGHTS_REQUIRED")
    options = service.settings.app.get("video", {})
    info = inspect_video(
        service.settings.root,
        relative_path,
        options.get("max_duration_seconds", 60),
        options.get("max_bytes", 104857600),
    )
    media_dir = inside(service.settings.root, service.settings.app["media_dir"])
    media_dir.mkdir(parents=True, exist_ok=True)
    target = media_dir / (info["sha256"] + ".mp4")
    if not target.exists():
        shutil.copyfile(inside(service.settings.root, relative_path), target)
    with service.db.session.begin() as session:
        draft = session.get(Draft, draft_id)
        if (
            not draft
            or draft.state == "published"
            or session.scalar(select(Intent).where(Intent.draft_id == draft_id))
        ):
            raise AgentError("DRAFT_STATE_CONFLICT", 409)
        payload = dict(draft.current)
        payload["video"] = {
            **info,
            "path": target.relative_to(service.settings.root).as_posix(),
            "rights_basis": rights_basis,
            "added_at": now(),
        }
        draft.revision += 1
        draft.current, draft.state, draft.scheduled_at = payload, "review_pending", None
        session.execute(update(Approval).where(Approval.draft_id == draft_id).values(revoked=True))
        session.add(
            DraftRevision(
                draft_id=draft_id,
                revision=draft.revision,
                payload=payload,
                config_id=draft.config_id,
            )
        )
        service.db.audit(session, actor, "attach_video", draft_id, sha256=info["sha256"])
        return {**info, "revision": draft.revision, "content_hash": fingerprint(payload)}


class VideoBackend:
    """Connect to a separately deployed generator with the documented /jobs protocol."""

    def __init__(self, settings, transport=None):
        self.settings = settings
        self.options = settings.app.get("video", {})
        self.client = httpx.Client(trust_env=False, timeout=30, transport=transport)

    def submit(self, scenario):
        if self.options.get("backend", "disabled") != "http":
            raise AgentError("VIDEO_BACKEND_NOT_CONNECTED")
        limit = self.options.get("max_cost_rub", 0)
        if limit <= 0:
            raise AgentError("VIDEO_BUDGET_NOT_CONFIGURED")
        # This adapter returns a proposed job; paid execution requires a reserved external budget.
        # No provider is silently invoked during project setup or test runs.
        raise AgentError("VIDEO_PAID_EXECUTION_REQUIRES_CAMPAIGN_RESERVATION")

    def status(self):
        return {
            "backend": self.options.get("backend", "disabled"),
            "generation_enabled": False,
            "live_verified": False,
            "ready_video_import": True,
        }
