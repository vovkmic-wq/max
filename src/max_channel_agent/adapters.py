"""OpenCode stateless generation and explicit MAX delivery outcomes."""

import json
import os
import re
import uuid
from dataclasses import dataclass

import httpx

from .config import AgentError, inside, parse_json


def extract_object(text):
    stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        value = parse_json(stripped)
    except AgentError as exc:
        raise AgentError("INVALID_EDITOR_RESULT") from exc
    if not isinstance(value, dict):
        raise AgentError("INVALID_EDITOR_RESULT")
    return value


class OpenCode:
    def __init__(self, settings, transport=None):
        self.options = settings.app["opencode"]
        self.mode = self.options["adapter_mode"]
        self.root = settings.root
        self.base_url = os.getenv(self.options["base_url_env"], "").rstrip("/")
        self.model = os.getenv(self.options["model_id_env"], self.options.get("model_id", ""))
        self.secret = os.getenv(self.options["auth_secret_env"], "")
        access_path = self.options.get("local_access_path")
        if access_path:
            path = inside(self.root, access_path)
            if path.exists():
                access = parse_json(path.read_text(encoding="utf-8"))
                self.base_url = self.base_url or access["base_url"]
                self.secret = self.secret or access["password"]
        self.auth = httpx.BasicAuth("opencode", self.secret) if self.secret else None
        self.client = httpx.Client(
            timeout=self.options["task_timeout_seconds"], trust_env=False, transport=transport
        )
        self.path = self.options.get("generate_path", "/api/experimental/generate")

    def probe(self):
        if self.mode == "fake":
            return {"state": "offline", "runtime": "fake", "live_verified": False}
        if not self.base_url:
            return {"state": "needs_configuration", "live_verified": False}
        try:
            response = self.client.get(self.base_url + "/api/info", auth=self.auth)
            response.raise_for_status()
            info = response.json()
            return {
                "state": "available",
                "live_verified": False,
                "required_version": self.options["required_version"],
                "reported_version": info.get("version") if isinstance(info, dict) else None,
            }
        except (httpx.HTTPError, ValueError):
            return {"state": "unavailable", "live_verified": False}

    def generate_text(self, prompt):
        if self.mode != "live" or not self.base_url:
            raise AgentError("OPENCODE_NOT_CONFIGURED")
        payload = {"prompt": prompt}
        if self.model:
            provider, model = self.model.split("/", 1)
            payload["model"] = {"providerID": provider, "id": model}
        try:
            session_id = None
            if self.options.get("generate_transport") == "session":
                created = self.client.post(
                    self.base_url + "/api/session",
                    auth=self.auth,
                    json={
                        "title": "MAX editorial task",
                        "model": payload.get("model"),
                        "location": {
                            "directory": str(inside(self.root, self.options["runtime_dir"]))
                        },
                        "permissions": [{"action": "*", "resource": "*", "effect": "deny"}],
                    },
                )
                created.raise_for_status()
                session_id = created.json().get("data", {}).get("id")
                if not session_id or not re.fullmatch(r"ses[a-zA-Z0-9_-]+", session_id):
                    raise AgentError("OPENCODE_SESSION_INVALID")
            try:
                path = f"/api/session/{session_id}/generate" if session_id else self.path
                response = self.client.post(
                    self.base_url + path,
                    json={"prompt": prompt} if session_id else payload,
                    auth=self.auth,
                )
            finally:
                if session_id:
                    try:
                        self.client.post(
                            self.base_url + f"/api/session/{session_id}/interrupt",
                            auth=self.auth,
                            timeout=5,
                        )
                        self.client.delete(
                            self.base_url + f"/api/session/{session_id}", auth=self.auth, timeout=5
                        )
                    except httpx.HTTPError:
                        pass
            if response.status_code in {401, 403}:
                raise AgentError("OPENCODE_ACCESS_DENIED")
            if response.status_code == 503:
                raise AgentError("OPENCODE_PROVIDER_UNAVAILABLE")
            response.raise_for_status()
            data = response.json()
            text = data.get("data", data).get("text", "")
            if not isinstance(text, str) or not text.strip():
                raise AgentError("OPENCODE_EMPTY_RESPONSE")
            return text, data.get("usage", {})
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise AgentError("OPENCODE_GENERATION_FAILED") from exc

    def run(self, task_type, context):
        if self.mode == "fake":
            if task_type == "draft":
                material = context["materials"][0]
                text = material["title"] + "\n\n" + material["text"]
                if material["url"]:
                    text += "\n\nИсточник: " + material["url"]
                return {
                    "title": material["title"],
                    "body": text,
                    "language": "ru",
                    "source_ids": [material["id"]],
                    "decision": "review",
                    "reason_codes": ["OFFLINE_FIXTURE"],
                    "claims": [],
                    "confidence": 0,
                    "payload": {},
                }, {}
            if task_type == "cluster":
                return {"same_event": False}, {}
            if task_type == "classify":
                return {"relevance": 1, "decision": "review"}, {}
            if task_type == "verify":
                return {"verified": False, "issues": ["OFFLINE_FIXTURE"]}, {}
            if task_type == "translate":
                raise AgentError("OFFLINE_TRANSLATION_UNAVAILABLE")
            if task_type == "bootstrap":
                return {
                    "name": context["channel"]["name"],
                    "description": context["channel"]["theme"],
                    "calendar": context["channel"]["content_pillars"],
                    "note": "Локальный шаблон; не результат модели",
                }, {}
            return {"note": "Локальный план; генерация моделью выключена"}, {}
        instruction = (self.root / "prompts/EDITOR_AGENT_PROMPT.md").read_text(encoding="utf-8")
        output = {
            "draft": '{"title":"...","body":"...","language":"ru","source_ids":[],"decision":"accept|reject|review","reason_codes":[],"claims":[{"text":"...","material_id":"...","quote":"exact original fragment"}],"confidence":0.8,"payload":{}}',
            "cluster": '{"same_event":true,"reason":"..."}',
            "translate": '{"text":"Russian translation"}',
            "classify": '{"relevance":0.8,"decision":"accept|reject|review","reason":"..."}',
            "verify": '{"verified":true,"issues":[]}',
            "bootstrap": '{"name":"...","description":"...","welcome":"...","calendar":[]}',
            "growth_plan": '{"hypothesis":"...","action":"...","metric":"...","stop_condition":"..."}',
        }[task_type]
        prompt = instruction + "\nFor this service task use this exact JSON shape:\n" + output
        prompt += "\nTask type: " + task_type + "\nUNTRUSTED MATERIALS AND TRUSTED CONFIG:\n"
        prompt += json.dumps(context, ensure_ascii=False)
        for attempt in range(self.options["max_format_repairs"] + 1):
            text, usage = self.generate_text(prompt)
            try:
                return extract_object(text), usage
            except AgentError:
                if attempt == self.options["max_format_repairs"]:
                    raise
                # Do not send the failed output back; it may contain injection or invented secrets.
                prompt += "\nReturn valid JSON only. No markdown fences or commentary."
        raise AgentError("INVALID_EDITOR_RESULT")


@dataclass
class Delivery:
    state: str
    external_id: str | None = None
    permalink: str | None = None
    retry_after: float = 0


class MaxAPI:
    def __init__(self, settings, transport=None):
        self.options = settings.app["max"]
        self.mode = self.options["adapter_mode"]
        self.base_url = self.options["api_base_url"].rstrip("/")
        self.token = os.getenv(self.options["token_env"], "")
        self.client = httpx.Client(
            timeout=self.options["request_timeout_seconds"], trust_env=False, transport=transport
        )

    def request(self, method, path, **kwargs):
        if not self.token:
            raise AgentError("MAX_TOKEN_REQUIRED")
        try:
            return self.client.request(
                method, self.base_url + path, headers={"Authorization": self.token}, **kwargs
            )
        except httpx.HTTPError as exc:
            raise AgentError("MAX_TRANSPORT_UNKNOWN") from exc

    def inspect(self, chat_id):
        if self.mode == "fake":
            return {
                "publish": True,
                "read": True,
                "edit": True,
                "remove": True,
                "create_channel": False,
                "live_verified": False,
            }
        response = self.request("GET", f"/chats/{chat_id}/members/me")
        if response.status_code != 200:
            raise AgentError("MAX_CHANNEL_ACCESS_DENIED")
        membership = response.json()
        admin = bool(membership.get("is_admin") or membership.get("is_owner"))
        permissions = membership.get("permissions", [])
        return {
            "publish": admin and (not permissions or "write" in permissions),
            "read": admin,
            "edit": admin,
            "remove": admin,
            "create_channel": False,
            "live_verified": True,
        }

    def publish(self, chat_id, text, attachment=None):
        if self.mode == "fake":
            return Delivery("confirmed", "offline-" + str(uuid.uuid4()), None)
        try:
            payload = {"text": text, "notify": True}
            if attachment:
                payload["attachments"] = [attachment]
            response = self.request("POST", "/messages", params={"chat_id": chat_id}, json=payload)
            if (
                response.status_code == 400
                and response.json().get("code") == "attachment.not.ready"
            ):
                return Delivery("retry_wait", retry_after=30)
            if response.status_code in {401, 403, 400, 404}:
                return Delivery("rejected")
            if response.status_code == 429:
                try:
                    delay = max(1, float(response.headers.get("Retry-After", "60")))
                except ValueError:
                    delay = 60
                return Delivery("retry_wait", retry_after=delay)
            if response.status_code != 200:
                return Delivery("unknown")
            message = response.json().get("message", {})
            mid = message.get("body", {}).get("mid")
            if not mid:
                return Delivery("unknown")
            return Delivery("confirmed", str(mid), message.get("url"))
        except (AgentError, ValueError, TypeError):
            return Delivery("unknown")

    def messages(self, chat_id, **params):
        if self.mode != "live":
            return []
        response = self.request("GET", "/messages", params={"chat_id": chat_id, **params})
        if response.status_code != 200:
            raise AgentError("MAX_READ_FAILED")
        return response.json().get("messages", [])

    def upload_video(self, path):
        if self.mode == "fake":
            return {"type": "video", "payload": {"token": "offline-video"}}
        response = self.request("POST", "/uploads", params={"type": "video"})
        if response.status_code != 200:
            raise AgentError("VIDEO_UPLOAD_UNAVAILABLE")
        data = response.json()
        from .network import validate_url

        url = data.get("url", "")
        host, addresses = validate_url(url)
        original = httpx.URL(url)
        with path.open("rb") as stream:
            uploaded = self.client.post(
                original.copy_with(host=addresses[0]),
                headers={"Host": original.netloc.decode()},
                extensions={"sni_hostname": host},
                files={"data": (path.name, stream, "video/mp4")},
            )
        if uploaded.status_code != 200:
            raise AgentError("VIDEO_UPLOAD_UNCONFIRMED")
        token = data.get("token") or uploaded.json().get("token")
        if not token:
            raise AgentError("VIDEO_UPLOAD_UNCONFIRMED")
        return {"type": "video", "payload": {"token": token}}

    def correct(self, message_id, text=None, remove=False):
        if self.mode == "fake":
            return True
        response = self.request(
            "DELETE" if remove else "PUT",
            "/messages",
            params={"message_id": message_id},
            **({} if remove else {"json": {"text": text}}),
        )
        if response.status_code != 200 or response.json().get("success") is not True:
            raise AgentError("MAX_CORRECTION_UNCONFIRMED")
        return True

    def close(self):
        self.client.close()
