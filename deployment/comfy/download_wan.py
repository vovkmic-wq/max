"""Download and verify pinned Wan weights for the isolated VM 109 runtime."""

import argparse
import hashlib
import json
import os
import shutil
import time
import urllib.request
from pathlib import Path


BASE = Path("/opt/max-video")
MODEL_ROOT = BASE / "models"



# Выполняем операцию checksum в рамках данного модуля.
def checksum(path):
    digest = hashlib.sha256()
    # Удерживаем контекст ресурсов или транзакции до завершения этого блока.
    with path.open("rb") as handle:
        # Последовательно обрабатываем элементы: iter(lambda: handle.read(8 * 1024 * 1024), b'').
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


# Выполняем операцию download в рамках данного модуля.
def download(model):
    path = (MODEL_ROOT / model["destination"]).resolve()
    # Обрабатываем ветвь при условии: not path.is_relative_to(MODEL_ROOT.resolve()).
    if not path.is_relative_to(MODEL_ROOT.resolve()):
        raise RuntimeError("Model destination must stay inside the dedicated model directory")
    path.parent.mkdir(parents=True, exist_ok=True)
    # Обрабатываем ветвь при условии: path.exists().
    if path.exists():
        # Обрабатываем ветвь при условии: path.stat().st_size == model['size'] and checksum(path) == model['sha256'].
        if path.stat().st_size == model["size"] and checksum(path) == model["sha256"]:
            print("Already verified: " + path.name, flush=True)
            return
        raise RuntimeError("Existing model differs; preserving it: " + path.name)
    partial = path.with_suffix(path.suffix + ".part")
    url = (
        "https://huggingface.co/" + model["repo"] + "/resolve/"
        + model["revision"] + "/" + model["file"] + "?download=true"
    )
    # Последовательно обрабатываем элементы: range(6).
    for attempt in range(6):
        offset = partial.stat().st_size if partial.exists() else 0
        # Обрабатываем ветвь при условии: offset == model['size'].
        if offset == model["size"]:
            break
        # Обрабатываем ветвь при условии: offset > model['size'].
        if offset > model["size"]:
            raise RuntimeError("Partial download is larger than expected")
        print(f"Download {path.name}: {offset}/{model['size']} bytes", flush=True)
        # Выполняем операцию с отдельной обработкой возможных ошибок.
        try:
            # A timestamp avoids expired signed redirects cached by intermediaries.
            request = urllib.request.Request(  # noqa: S310 - fixed HTTPS Hugging Face origin
                url + "&max_download=" + str(time.time_ns()),
                headers={"Range": f"bytes={offset}-", "User-Agent": "MAX-ComfyUI-Installer"},
            )
            # Удерживаем контекст ресурсов или транзакции до завершения этого блока.
            with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
                # Обрабатываем ветвь при условии: offset and (response.status != 206 or not response.headers.get('Content-Range', '').startswith(f'bytes {off….
                if offset and (
                    response.status != 206
                    or not response.headers.get("Content-Range", "").startswith(f"bytes {offset}-")
                ):
                    raise RuntimeError("Server did not honor the resume range")
                # Удерживаем контекст ресурсов или транзакции до завершения этого блока.
                with partial.open("ab" if offset else "wb") as output:
                    last_report = time.monotonic()
                    # Продолжаем цикл, пока выполняется условие: (block := response.read(1024 * 1024)).
                    while block := response.read(1024 * 1024):
                        # Обрабатываем ветвь при условии: output.tell() + len(block) > model['size'].
                        if output.tell() + len(block) > model["size"]:
                            raise RuntimeError("Download exceeds the expected size")
                        output.write(block)
                        # Обрабатываем ветвь при условии: time.monotonic() - last_report >= 30.
                        if time.monotonic() - last_report >= 30:
                            print(f"{path.name}: {output.tell()}/{model['size']} bytes", flush=True)
                            last_report = time.monotonic()
            # Обрабатываем ветвь при условии: partial.stat().st_size == model['size'].
            if partial.stat().st_size == model["size"]:
                break
        # Обрабатываем (OSError, RuntimeError) и выбираем допустимый исход.
        except (OSError, RuntimeError) as exc:
            print(f"Download attempt {attempt + 1}: {type(exc).__name__}", flush=True)
            # Обрабатываем ветвь при условии: attempt == 5.
            if attempt == 5:
                raise RuntimeError("Download could not finish; partial file retained") from None
            time.sleep(5)
    # Обрабатываем ветвь при условии: partial.stat().st_size != model['size'] or checksum(partial) != model['sha256'].
    if partial.stat().st_size != model["size"] or checksum(partial) != model["sha256"]:
        raise RuntimeError("Model size or SHA256 mismatch; partial file retained")
    partial.rename(path)
    shutil.chown(path, user="maxvideo", group="maxvideo")
    print("Verified SHA256: " + path.name, flush=True)



# Разбираем параметры запуска и выбираем сценарий выполнения.
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    # Обрабатываем ветвь при условии: os.name != 'posix' or os.geteuid() != 0 or shutil.which('pveversion').
    if os.name != "posix" or os.geteuid() != 0 or shutil.which("pveversion"):
        raise RuntimeError("Run only inside the dedicated Linux guest")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    # Последовательно обрабатываем элементы: manifest['models'].
    for model in manifest["models"]:
        download(model)
    print("WAN_MODELS_VERIFIED", flush=True)


# Обрабатываем ветвь при условии: __name__ == '__main__'.
if __name__ == "__main__":
    main()
