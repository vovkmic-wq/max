#!/usr/bin/env bash
# Run inside VM 109; uses the existing Vulkan driver without changing llama.cpp.
set -euo pipefail
if [[ $(id -u) != 0 ]] || command -v pveversion >/dev/null; then
  echo 'Run as root inside the Linux GPU guest, never on the Proxmox host.' >&2
  exit 1
fi
SCRIPT_DIR=$(cd -- "$(dirname -- "$0")" && pwd)
RUNTIME=/opt/max-video/runtime
RELEASE=master-945-a1ded76
ARCHIVE=sd-master-a1ded76-bin-Linux-Ubuntu-24.04-x86_64-vulkan.zip
ARCHIVE_SHA=e65f3c4cf3a0c4c5aed5120ab449be7c883db6c70648bcc56ca55b246b9d8161
for executable in curl python3 nft; do
  command -v "$executable" >/dev/null || { echo "Required tool missing: $executable" >&2; exit 1; }
done
id maxvideo >/dev/null 2>&1 || useradd --system --create-home --home-dir /opt/max-video --shell /usr/sbin/nologin maxvideo
usermod -a -G render maxvideo
install -d -o maxvideo -g maxvideo "$RUNTIME" /opt/max-video/models/quantized
if [[ ! -f "$RUNTIME/vulkan.zip" ]]; then
  curl --fail --location --retry 3 "https://github.com/leejet/stable-diffusion.cpp/releases/download/$RELEASE/$ARCHIVE" -o "$RUNTIME/vulkan.zip"
fi
echo "$ARCHIVE_SHA  $RUNTIME/vulkan.zip" | sha256sum -c -
python3 -c 'import zipfile; zipfile.ZipFile("/opt/max-video/runtime/vulkan.zip").extractall("/opt/max-video/runtime")'
chmod 755 "$RUNTIME/sd-cli" "$RUNTIME/sd-server"
chown -R maxvideo:maxvideo "$RUNTIME"
install -m 644 "$SCRIPT_DIR/download_wan.py" /opt/max-video/download_wan.py
install -m 644 "$SCRIPT_DIR/wan-models.json" /opt/max-video/wan-models.json
python3 /opt/max-video/download_wan.py /opt/max-video/wan-models.json
if [[ ! -f /opt/max-video/models/quantized/wan21-q5_0.gguf ]]; then
  runuser -u maxvideo -- env LD_LIBRARY_PATH="$RUNTIME" "$RUNTIME/sd-cli" \
    -M convert -m /opt/max-video/models/diffusion_models/wan2.1_t2v_1.3B_fp16.safetensors \
    -o /opt/max-video/models/quantized/wan21-q5_0.gguf --type q5_0 --backend cpu -t 2
fi
echo 'b99a648839de55cd0014077ff5793a342dede6a2144cf295bed9809285c18fe4e  /opt/max-video/models/quantized/wan21-q5_0.gguf' | sha256sum -c -
install -m 644 "$SCRIPT_DIR/vm109-max-wan.service" /etc/systemd/system/max-wan.service
install -m 644 "$SCRIPT_DIR/vm109-max-video-access.service" /etc/systemd/system/max-video-access.service
install -m 644 "$SCRIPT_DIR/vm109-max-video-access.nft" /etc/max-video-access.nft
nft --check -f /etc/max-video-access.nft
systemd-analyze verify /etc/systemd/system/max-wan.service /etc/systemd/system/max-video-access.service
systemctl daemon-reload
systemctl enable --now max-video-access.service max-wan.service
systemctl is-active max-wan.service
