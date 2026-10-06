"""Cross-platform commands. No implicit external posting during setup or demo."""

import argparse
import json
import os
import secrets
import shutil
import sys
import time
from pathlib import Path

from .config import AgentError, Settings
from .db import Database
from .service import Service


def load_env(root):
    path = root / ".env.local"
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


def initialize(root):
    for name in ("app", "sources"):
        target = root / f"config/{name}.json"
        if not target.exists():
            shutil.copy2(root / f"config/{name}.example.json", target)
    env = root / ".env.local"
    if not env.exists():
        env.write_text(
            "# Local panel secrets. Never copy into prompts or release archives.\n"
            + "\n".join(
                f"{key}={secrets.token_urlsafe(32)}"
                for key in (
                    "APP_AUTH_SECRET",
                    "APP_EDITOR_SECRET",
                    "APP_VIEWER_SECRET",
                    "MAX_WEBHOOK_SECRET",
                    "TELEGRAM_WEBHOOK_SECRET",
                )
            )
            + "\n",
            encoding="utf-8",
        )
        if os.name != "nt":
            env.chmod(0o600)
    load_env(root)


def build_service(root):
    load_env(root)
    settings = Settings.load(root)
    db = Database(settings)
    db.initialize()
    service = Service(settings, db)
    service.activate()
    return service


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Агент каналов MAX")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("init", "doctor", "tick", "worker"):
        sub.add_parser(command)
    serve = sub.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8080)
    for command in ("backup", "restore"):
        sub.add_parser(command).add_argument("path", type=Path)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        if args.command == "init":
            initialize(root)
            print("Локальные настройки готовы. Ключи панели находятся в .env.local.")
            return 0
        if args.command == "restore":
            from .backup import restore

            load_env(root)
            settings = Settings.load(root)
            db = Database(settings)
            db.initialize()
            service = Service(settings, db)
            key = os.getenv("MAX_AGENT_BACKUP_KEY")
            if not key:
                raise AgentError("BACKUP_KEY_REQUIRED")
            try:
                restore(service, args.path, key.encode())
                print(json.dumps({"restored": True, "channels_paused": True}))
            finally:
                service.close()
            return 0
        service = build_service(root)
        try:
            if args.command == "doctor":
                print(
                    json.dumps(
                        {
                            "status": "configured",
                            "database": service.db.engine.dialect.name,
                            "opencode": service.editor.probe(),
                            "max_mode": service.publisher.mode,
                            "enabled_channels": sum(
                                c["enabled"] for c in service.settings.topic["channels"]
                            ),
                            "production_accepted": False,
                        },
                        ensure_ascii=False,
                    )
                )
            elif args.command == "tick":
                print(json.dumps({"confirmed_publications": service.tick()}))
            elif args.command == "worker":
                while True:
                    service.tick()
                    time.sleep(5)
            elif args.command == "serve":
                import uvicorn
                from .api import create_app

                if not os.getenv(service.settings.app["api"]["auth_secret_env"]):
                    raise AgentError("PANEL_SECRET_REQUIRED")
                uvicorn.run(
                    create_app(service, run_worker=True),
                    host=args.host,
                    port=args.port,
                    access_log=False,
                )
            else:
                from .backup import backup

                key = os.getenv("MAX_AGENT_BACKUP_KEY")
                if not key:
                    raise AgentError("BACKUP_KEY_REQUIRED")
                if args.command == "backup":
                    print(json.dumps({"sha256": backup(service, args.path, key.encode())}))
        finally:
            service.close()
        return 0
    except AgentError as exc:
        print(json.dumps({"code": exc.code}, ensure_ascii=False))
        return 1
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
