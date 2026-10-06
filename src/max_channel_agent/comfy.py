"""One real generator: approved ComfyUI API workflow, async history and reconciliation."""

import copy
import os
import re
from urllib.parse import urlsplit

import httpx

from .config import AgentError, fingerprint, inside, parse_json


class ComfyUI:
    def __init__(self, settings, transport=None):
        self.settings = settings
        self.options = settings.app.get("video", {})
        self.base_url = os.getenv(self.options.get("base_url_env", "COMFYUI_BASE_URL"), "").rstrip(
            "/"
        )
        self.client = httpx.Client(
            timeout=30, trust_env=False, follow_redirects=False, transport=transport
        )

    def configuration(self):
        if self.options.get("backend") != "comfyui" or not self.base_url:
            raise AgentError("VIDEO_BACKEND_NOT_CONNECTED")
        parsed = urlsplit(self.base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise AgentError("GENERATOR_URL_INVALID")
        workflow_file = inside(
            self.settings.root, self.options.get("workflow_path", "config/comfy/workflow.json")
        )
        if not workflow_file.is_file():
            raise AgentError("VIDEO_WORKFLOW_REQUIRED")
        workflow = parse_json(
            inside(
                self.settings.root, self.options.get("workflow_path", "config/comfy/workflow.json")
            ).read_text(encoding="utf-8-sig")
        )
        if fingerprint(workflow) != self.options.get("workflow_sha256"):
            raise AgentError("GENERATOR_WORKFLOW_NOT_APPROVED")
        if not isinstance(workflow, dict) or not workflow:
            raise AgentError("GENERATOR_WORKFLOW_INVALID")
        allowed = self.options.get("allowed_node_classes", [])
        for node in workflow.values():
            if (
                not isinstance(node, dict)
                or not isinstance(node.get("inputs"), dict)
                or node.get("class_type") not in allowed
            ):
                raise AgentError("GENERATOR_NODE_NOT_APPROVED")
        return workflow

    @property
    def binding_hash(self):
        return fingerprint({"base_url": self.base_url, "options": self.options})

    def status(self):
        try:
            self.configuration()
        except (AgentError, OSError):
            return {"state": "needs_configuration", "backend": "comfyui", "live_verified": False}
        try:
            r = self.client.get(self.base_url + "/system_stats")
            return {
                "state": "available" if r.status_code == 200 else "unavailable",
                "backend": "comfyui",
                "live_verified": False,
            }
        except httpx.HTTPError:
            return {"state": "unavailable", "backend": "comfyui", "live_verified": False}

    def prepare(self, scene, seed):
        workflow = copy.deepcopy(self.configuration())
        values = {
            "positive": scene["prompt"],
            "negative": scene.get("negative_prompt", ""),
            "seed": seed,
            "frames": max(
                1, round(scene["duration_seconds"] * self.options.get("generation_fps", 16))
            ),
        }
        for binding in self.options.get("bindings", []):
            node, field, value = binding["node"], binding["input"], binding["value"]
            if node not in workflow or field not in workflow[node]["inputs"] or value not in values:
                raise AgentError("WORKFLOW_BINDING_INVALID")
            workflow[node]["inputs"][field] = values[value]
        if not any(b.get("value") == "positive" for b in self.options.get("bindings", [])):
            raise AgentError("WORKFLOW_PROMPT_BINDING_REQUIRED")
        return workflow

    def submit(self, scene, request_id, seed):
        workflow = self.prepare(scene, seed)
        try:
            r = self.client.post(
                self.base_url + "/prompt",
                json={
                    "prompt": workflow,
                    "client_id": request_id,
                    "extra_data": {"max_request_id": request_id},
                },
            )
        except httpx.HTTPError as exc:
            raise AgentError("VIDEO_SUBMIT_UNKNOWN") from exc
        if r.status_code == 400:
            raise AgentError("VIDEO_WORKFLOW_REJECTED")
        if r.status_code != 200:
            raise AgentError("VIDEO_SUBMIT_UNKNOWN")
        try:
            remote_id = r.json()["prompt_id"]
            if not isinstance(remote_id, str) or not re.fullmatch(
                r"[A-Za-z0-9_-]{1,128}", remote_id
            ):
                raise ValueError
            return remote_id
        except (ValueError, KeyError, TypeError) as exc:
            raise AgentError("VIDEO_SUBMIT_UNKNOWN") from exc

    def poll(self, remote_id):
        if not isinstance(remote_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", remote_id):
            raise AgentError("GENERATOR_JOB_ID_INVALID")
        try:
            r = self.client.get(self.base_url + "/history/" + remote_id)
            r.raise_for_status()
            history = r.json().get(remote_id)
        except (httpx.HTTPError, ValueError, AttributeError) as exc:
            raise AgentError("VIDEO_HISTORY_UNAVAILABLE") from exc
        if not history:
            return {"state": "running"}
        if history.get("status", {}).get("status_str") == "error":
            return {"state": "failed"}
        outputs = history.get("outputs", {})
        for output in outputs.values():
            for field in ("videos", "gifs", "images"):
                for asset in output.get(field, []):
                    if asset.get("filename", "").lower().endswith(".mp4"):
                        return {"state": "completed", "asset": asset}
        if history.get("status", {}).get("completed"):
            return {"state": "failed"}
        return {"state": "running"}

    def reconcile(self, request_id):
        try:
            history = self.client.get(self.base_url + "/history")
            queue = self.client.get(self.base_url + "/queue")
            history.raise_for_status()
            queue.raise_for_status()
            prompts = [v.get("prompt", []) for v in history.json().values()]
            q = queue.json()
            prompts.extend(q.get("queue_running", []) + q.get("queue_pending", []))
            ids = {
                p[1]
                for p in prompts
                if isinstance(p, list)
                and len(p) > 3
                and isinstance(p[3], dict)
                and p[3].get("max_request_id") == request_id
            }
            return next(iter(ids)) if len(ids) == 1 else None
        except (httpx.HTTPError, ValueError, AttributeError, TypeError) as exc:
            raise AgentError("VIDEO_RECONCILE_UNAVAILABLE") from exc

    def download(self, asset, relative):
        name, subfolder = asset.get("filename", ""), asset.get("subfolder", "")
        if (
            not re.fullmatch(r"[\w .-]+\.mp4", name, re.I)
            or any(x in subfolder for x in ("..", "\\", ":"))
            or subfolder.startswith("/")
        ):
            raise AgentError("GENERATOR_OUTPUT_PATH_INVALID")
        path = inside(self.settings.root, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".partial")
        size = 0
        try:
            with self.client.stream(
                "GET",
                self.base_url + "/view",
                params={"filename": name, "subfolder": subfolder, "type": "output"},
            ) as r:
                r.raise_for_status()
                with temporary.open("wb") as stream:
                    for chunk in r.iter_bytes():
                        size += len(chunk)
                        if size > self.options.get("max_bytes", 104857600):
                            raise AgentError("VIDEO_TOO_LARGE")
                        stream.write(chunk)
            temporary.replace(path)
        except httpx.HTTPError as exc:
            raise AgentError("VIDEO_DOWNLOAD_FAILED") from exc
        finally:
            temporary.unlink(missing_ok=True)
        return relative

    def close(self):
        self.client.close()
