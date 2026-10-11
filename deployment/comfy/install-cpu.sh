#!/usr/bin/env bash
# Run inside a dedicated Ubuntu 24.04 guest, never on the Proxmox host.
set -euo pipefail
COMFY_RELEASE="${COMFY_RELEASE:-v0.39.0}"
COMFY_BIND="${COMFY_BIND:-127.0.0.1}"
COMFY_ALLOW_IPV4="${COMFY_ALLOW_IPV4:-}"
if [[ $(id -u) != 0 ]]; then echo 'Root inside the guest is required.' >&2; exit 1; fi
if command -v pveversion >/dev/null; then echo 'Refusing installation on a Proxmox host.' >&2; exit 1; fi
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends python3 python3-venv git ca-certificates ffmpeg libgl1 libglib2.0-0 curl nftables
if [[ "$COMFY_BIND" != '127.0.0.1' ]]; then
  [[ "$COMFY_ALLOW_IPV4" =~ ^[0-9.,\ ]+$ ]] || { echo 'Explicit client IPv4 allowlist required.' >&2; exit 1; }
  cat > /etc/nftables.conf <<EOF
#!/usr/sbin/nft -f
flush ruleset
table inet comfyui_access {
  chain input {
    type filter hook input priority 0; policy accept;
    iifname "lo" tcp dport 8188 accept
    ip saddr { ${COMFY_ALLOW_IPV4} } tcp dport 8188 accept
    tcp dport 8188 reject
  }
}
EOF
  nft --check --file /etc/nftables.conf
  nft --file /etc/nftables.conf
  systemctl enable nftables
fi
id comfyui >/dev/null 2>&1 || useradd --system --create-home --home-dir /opt/max-comfyui --shell /usr/sbin/nologin comfyui
if [[ ! -d /opt/max-comfyui/ComfyUI ]]; then
  runuser -u comfyui -- git clone --depth 1 --branch "$COMFY_RELEASE" https://github.com/Comfy-Org/ComfyUI.git /opt/max-comfyui/ComfyUI
fi
[[ $(git -C /opt/max-comfyui/ComfyUI -c safe.directory=/opt/max-comfyui/ComfyUI describe --tags --exact-match) == "$COMFY_RELEASE" ]]
runuser -u comfyui -- python3 -m venv /opt/max-comfyui/venv
runuser -u comfyui -- /opt/max-comfyui/venv/bin/pip install --upgrade pip
runuser -u comfyui -- /opt/max-comfyui/venv/bin/pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
runuser -u comfyui -- /opt/max-comfyui/venv/bin/pip install -r /opt/max-comfyui/ComfyUI/requirements.txt
runuser -u comfyui -- /opt/max-comfyui/venv/bin/pip check
runuser -u comfyui -- /opt/max-comfyui/venv/bin/pip freeze > /opt/max-comfyui/requirements.installed.txt
cat > /etc/systemd/system/max-comfyui.service <<EOF
[Unit]
Description=ComfyUI for MAX (CPU)
After=network-online.target
Wants=network-online.target
[Service]
User=comfyui
Group=comfyui
WorkingDirectory=/opt/max-comfyui/ComfyUI
ExecStart=/opt/max-comfyui/venv/bin/python main.py --cpu --listen ${COMFY_BIND} --port 8188 --disable-auto-launch --disable-all-custom-nodes
Restart=on-failure
RestartSec=10
Environment=OMP_NUM_THREADS=2
Environment=MKL_NUM_THREADS=2
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/max-comfyui
UMask=0077
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now max-comfyui.service
for attempt in $(seq 1 90); do
  if curl --fail --silent http://127.0.0.1:8188/system_stats > /opt/max-comfyui/system-stats.json; then
    echo 'ComfyUI API ready'; exit 0
  fi
  sleep 2
done
systemctl status max-comfyui.service --no-pager
exit 1
