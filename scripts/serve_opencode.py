"""Managed OpenCode process. Capture generated credentials without printing them."""

import argparse
import json
import os
import signal
import subprocess
from pathlib import Path


# Разбираем параметры запуска и выбираем сценарий выполнения.
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--port", type=int, default=4107)
    args = parser.parse_args()
    runtime = args.root.resolve() / "data/opencode-runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    child = subprocess.Popen(
        [args.binary, "serve", "--hostname", "127.0.0.1", "--port", str(args.port)],
        cwd=runtime,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )

    # Операция stop: данного модуля.
    def stop(*_):
        child.terminate()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    # Выполняем операцию с отдельной обработкой возможных ошибок.
    try:
        # Последовательно обрабатываем элементы: child.stdout.
        for line in child.stdout:
            # Обрабатываем ветвь при условии: line.startswith('server password ').
            if line.startswith("server password "):
                access = runtime / "access.json"
                access.write_text(
                    json.dumps(
                        {
                            "base_url": f"http://127.0.0.1:{args.port}",
                            "password": line.strip().split(" ", 2)[2],
                        }
                    ),
                    encoding="utf-8",
                )
                # Обрабатываем ветвь при условии: os.name != 'nt'.
                if os.name != "nt":
                    access.chmod(0o600)
                print("OpenCode ready; local access saved privately.", flush=True)
            # All other output is suppressed: backend errors can contain sensitive headers.
        return child.wait()
    finally:
        # Завершаем работу и освобождаем ресурсы независимо от результата.
        child.terminate()


# Обрабатываем ветвь при условии: __name__ == '__main__'.
if __name__ == "__main__":
    raise SystemExit(main())
