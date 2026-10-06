"""Authenticated Russian management interface and durable webhook endpoints."""

import hmac
import math
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, Depends, FastAPI, Header, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select, text

from .config import AgentError, Settings, fingerprint
from .db import (
    Approval,
    Audit,
    Campaign,
    Channel,
    Cursor,
    Draft,
    DraftRevision,
    Intent,
    Job,
    Metric,
    serialize,
)


def create_app(service, run_worker=False):
    stop = threading.Event()

    def work():
        while not stop.wait(5):
            try:
                service.tick()
            except Exception:
                # Never print raw exceptions from token-bearing transports.
                service.config_error = "WORKER_REQUIRES_ATTENTION"

    @asynccontextmanager
    async def lifespan(app):
        worker = threading.Thread(target=work, daemon=True) if run_worker else None
        if worker:
            worker.start()
        yield
        stop.set()
        if worker:
            worker.join(timeout=5)

    app = FastAPI(title="Агент каналов MAX", lifespan=lifespan)
    app.state.service = service

    @app.exception_handler(AgentError)
    async def handled(request, error):
        return JSONResponse(
            {"code": error.code, "safe_message": error.code}, status_code=error.status
        )

    @app.middleware("http")
    async def limits(request, call_next):
        try:
            length = int(request.headers.get("content-length", "0"))
        except ValueError:
            return JSONResponse({"code": "INVALID_CONTENT_LENGTH"}, status_code=400)
        if length > 1048576:
            return JSONResponse({"code": "REQUEST_TOO_LARGE"}, status_code=413)
        # Also bound chunked requests before JSON parsing; Content-Length is not trusted.
        if request.method in {"POST", "PUT", "PATCH"}:
            received = bytearray()
            async for chunk in request.stream():
                received.extend(chunk)
                if len(received) > 1048576:
                    return JSONResponse({"code": "REQUEST_TOO_LARGE"}, status_code=413)
            request._body = bytes(received)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'"
        )
        return response

    def auth(authorization: str | None = Header(default=None)):
        if not authorization or not authorization.startswith("Bearer "):
            raise AgentError("AUTH_REQUIRED", 401)
        supplied = authorization[7:]
        secrets = {
            "owner": os.getenv(service.settings.app["api"]["auth_secret_env"], ""),
            "editor": os.getenv("APP_EDITOR_SECRET", ""),
            "viewer": os.getenv("APP_VIEWER_SECRET", ""),
        }
        for role, secret in secrets.items():
            if secret and hmac.compare_digest(secret, supplied):
                return role
        raise AgentError("AUTH_INVALID", 401)

    def editor(role=Depends(auth)):
        if role not in {"owner", "editor"}:
            raise AgentError("ROLE_FORBIDDEN", 403)
        return role

    def owner(role=Depends(auth)):
        if role != "owner":
            raise AgentError("ROLE_FORBIDDEN", 403)
        return role

    def rows(model):
        with service.db.session() as session:
            return [serialize(row) for row in session.scalars(select(model).limit(1000))]

    @app.get("/")
    def dashboard():
        return FileResponse(Path(__file__).parent / "static/index.html")

    @app.get("/static/{name}")
    def static(name: str):
        if name not in {"dashboard.js", "style.css"}:
            raise AgentError("NOT_FOUND", 404)
        return FileResponse(Path(__file__).parent / "static" / name)

    @app.get("/health/live")
    def live():
        return {"status": "alive"}

    @app.get("/health/ready")
    def ready():
        try:
            service.refresh()
            with service.db.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception:
            return JSONResponse({"status": "not_ready"}, status_code=503)
        if service.config_error:
            return JSONResponse(
                {"status": "not_ready", "code": service.config_error}, status_code=503
            )
        return {"status": "ready", "live_accepted": False}

    @app.get("/api/v1/integrations/status", dependencies=[Depends(auth)])
    def integrations():
        return {
            "opencode": service.editor.probe(),
            "max": {
                "mode": service.publisher.mode,
                "token_configured": bool(service.publisher.token),
                "live_verified": any(c["capabilities"].get("live_verified") for c in rows(Channel)),
            },
            "database": service.db.engine.dialect.name,
            "configuration": service.config_error or "valid",
        }

    @app.get("/api/v1/{collection}", dependencies=[Depends(auth)])
    def collections(collection: str):
        models = {
            "channels": Channel,
            "sources": Cursor,
            "drafts": Draft,
            "publications": Intent,
            "jobs": Job,
            "audit": Audit,
            "campaigns": Campaign,
        }
        if collection == "drafts":
            return [{**row, "content_hash": fingerprint(row["current"])} for row in rows(Draft)]
        if collection == "channels":
            return [
                {
                    **row,
                    "name": service.settings.channel(row["id"])["name"],
                    "theme": service.settings.channel(row["id"])["theme"],
                    "mode": service.settings.channel(row["id"])["publication"]["mode"],
                }
                for row in rows(Channel)
            ]
        if collection not in models:
            raise AgentError("NOT_FOUND", 404)
        return rows(models[collection])

    @app.post("/api/v1/config/validate", dependencies=[Depends(owner)])
    def validate_config():
        candidate = Settings.load(service.settings.root)
        return {
            "valid": True,
            "hash": candidate.hash,
            "changed": candidate.hash != service.settings.hash,
        }

    @app.post("/api/v1/config/activate")
    def activate(role=Depends(owner)):
        candidate = Settings.load(service.settings.root)
        service.activate(candidate, role)
        return {"hash": candidate.hash}

    @app.post("/api/v1/channels/{channel_id}/connect")
    def connect(channel_id: str, body: dict = Body(), role=Depends(owner)):
        return service.connect(channel_id, str(body.get("chat_id", "")), role)

    @app.post("/api/v1/channels/{channel_id}/{action}")
    def channel_action(channel_id: str, action: str, role=Depends(owner)):
        if action == "bootstrap":
            return service.model_task(
                "bootstrap", channel_id, {"channel": service.settings.channel(channel_id)}
            )
        if action == "growth-plan":
            return service.growth_plan(channel_id)
        if action not in {"pause", "resume"}:
            raise AgentError("NOT_FOUND", 404)
        service.pause(channel_id, action == "pause", role)
        return {"paused": action == "pause"}

    @app.post("/api/v1/sources/{source_id}/collect")
    def collect(source_id: str, role=Depends(owner)):
        source = service.settings.source(source_id)
        if not source["enabled"]:
            raise AgentError("SOURCE_DISABLED")
        import uuid

        with service.db.session.begin() as session:
            service.enqueue(session, "collect", source_id, 0, f"manual:{source_id}:{uuid.uuid4()}")
            service.db.audit(session, role, "collect_requested", source_id)
        return {"queued": True}

    @app.post("/api/v1/drafts/{draft_id}/approve")
    def approve(draft_id: str, body: dict = Body(), role=Depends(editor)):
        service.approve(draft_id, body.get("revision"), body.get("content_hash"), role)
        return {"scheduled": True}

    @app.post("/api/v1/drafts/{draft_id}/revise")
    def revise(draft_id: str, body: dict = Body(), role=Depends(editor)):
        service.revise(draft_id, body.get("revision"), body.get("body", ""), role)
        return {"revised": True}

    @app.post("/api/v1/drafts/{draft_id}/video")
    def video(draft_id: str, body: dict = Body(), role=Depends(owner)):
        from .media import attach_video

        return attach_video(
            service, draft_id, body.get("path", ""), body.get("rights_basis", ""), role
        )

    @app.post("/api/v1/drafts/{draft_id}/commercial")
    def commercial(draft_id: str, body: dict = Body(), role=Depends(owner)):
        from sqlalchemy import update

        with service.db.session.begin() as session:
            draft = session.get(Draft, draft_id)
            if (
                not draft
                or draft.revision != body.get("revision")
                or draft.state == "published"
                or session.scalar(select(Intent).where(Intent.draft_id == draft_id))
            ):
                raise AgentError("DRAFT_REVISION_CONFLICT", 409)
            draft.commercial = body.get("commercial") is True
            draft.state, draft.scheduled_at = "review_pending", None
            session.execute(
                update(Approval).where(Approval.draft_id == draft_id).values(revoked=True)
            )
            service.db.audit(session, role, "commercial_tag", draft_id, commercial=draft.commercial)
        return {"commercial": draft.commercial}

    @app.post("/api/v1/drafts/{draft_id}/reject")
    def reject(draft_id: str, body: dict = Body(), role=Depends(editor)):
        with service.db.session.begin() as session:
            draft = session.get(Draft, draft_id)
            if not draft or draft.revision != body.get("revision") or draft.state == "published":
                raise AgentError("DRAFT_REVISION_CONFLICT", 409)
            draft.state = "rejected"
            service.db.audit(session, role, "reject", draft_id)
        return {"rejected": True}

    @app.post("/api/v1/publications/{intent_id}/reconcile", dependencies=[Depends(owner)])
    def reconcile(intent_id: str):
        return {"state": service.reconcile(intent_id)}

    @app.post("/api/v1/publications/{intent_id}/correct")
    def correct(intent_id: str, body: dict = Body(), role=Depends(editor)):
        with service.db.session.begin() as session:
            intent = session.get(Intent, intent_id)
            if not intent or intent.state != "confirmed":
                raise AgentError("PUBLICATION_NOT_CONFIRMED", 409)
            draft = session.get(Draft, intent.draft_id)
            if body.get("revision") != draft.revision:
                raise AgentError("DRAFT_REVISION_CONFLICT", 409)
            remove = body.get("remove") is True
            text_value = body.get("body", "")
            if not remove:
                materials = service.db.export()["materials"]
                from .editorial import validate_draft

                candidate = {k: v for k, v in draft.current.items() if k not in {"checks", "video"}}
                candidate["body"] = text_value
                checks = validate_draft(
                    candidate,
                    [m for m in materials if m["story_id"] == draft.story_id],
                    service.settings.channel(draft.channel_id),
                )
                if set(checks) - {"EDITOR_REVIEW_REQUIRED"}:
                    raise AgentError("QUALITY_GATE_BLOCKED")
            service.publisher.correct(intent.external_id, text_value, remove)
            intent.state = "removed" if remove else "confirmed"
            if not remove:
                if "video" in draft.current:
                    candidate["video"] = draft.current["video"]
                candidate["checks"] = checks
                draft.current = candidate
                draft.revision += 1
                intent.body_hash = fingerprint(text_value)
                session.add(
                    DraftRevision(
                        draft_id=draft.id,
                        revision=draft.revision,
                        payload=candidate,
                        config_id=draft.config_id,
                    )
                )
            service.db.audit(session, role, "remove" if remove else "correct", intent_id)
        return {"confirmed": True}

    @app.get("/api/v1/reports/{channel_id}", dependencies=[Depends(auth)])
    def report(channel_id: str):
        return service.report(channel_id)

    @app.post("/api/v1/metrics")
    def metric(body: dict = Body(), role=Depends(owner)):
        channel_id = body.get("channel_id")
        service.settings.channel(channel_id)
        if body.get("name") not in {"subscribers", "views", "clicks", "revenue_rub", "spend_rub"}:
            raise AgentError("METRIC_INVALID")
        if (
            isinstance(body.get("value"), bool)
            or not isinstance(body.get("value"), (int, float))
            or not math.isfinite(body["value"])
            or body["value"] < 0
        ):
            raise AgentError("METRIC_INVALID")
        with service.db.session.begin() as session:
            session.add(
                Metric(
                    channel_id=channel_id, name=body["name"], value=body["value"], origin="manual"
                )
            )
            service.db.audit(session, role, "metric_import", channel_id)
        return {"saved": True}

    @app.post("/webhooks/{platform}")
    async def webhook(platform: str, request: Request):
        if platform not in {"max", "telegram"}:
            raise AgentError("NOT_FOUND", 404)
        env = "MAX_WEBHOOK_SECRET" if platform == "max" else "TELEGRAM_WEBHOOK_SECRET"
        header = "X-Max-Bot-Api-Secret" if platform == "max" else "X-Telegram-Bot-Api-Secret-Token"
        expected = os.getenv(env, "")
        supplied = request.headers.get(header, "")
        if not expected or not hmac.compare_digest(expected, supplied):
            raise AgentError("WEBHOOK_FORBIDDEN", 403)
        try:
            payload = await request.json()
        except ValueError as exc:
            raise AgentError("INVALID_EVENT") from exc
        if not isinstance(payload, dict):
            raise AgentError("INVALID_EVENT")
        accepted = service.receive(platform, payload)
        return {"accepted": accepted}

    return app
