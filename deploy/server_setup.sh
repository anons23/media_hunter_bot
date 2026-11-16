#!/usr/bin/env bash
# One-time hardening for a small VPS (1 CPU, 4 GB RAM, 10 GB disk).
# Safe to run again. Usage: sudo bash deploy/server_setup.sh [service-name]
set -euo pipefail
SERVICE="${1:-media-hunter.service}"

echo "== swap (1 GB) =="
if ! swapon --show | grep -q .; then
  fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  echo "swap enabled"
else
  echo "swap already present"
fi
sysctl -q vm.swappiness=10
echo 'vm.swappiness=10' > /etc/sysctl.d/99-media-hunter.conf

echo "== journald: limit logs to 200 MB =="
mkdir -p /etc/systemd/journald.conf.d
printf '[Journal]\nSystemMaxUse=200M\nMaxRetentionSec=14day\n' > /etc/systemd/journald.conf.d/99-media-hunter.conf
systemctl restart systemd-journald

echo "== auto-restart for ${SERVICE} =="
mkdir -p "/etc/systemd/system/${SERVICE}.d"
cat > "/etc/systemd/system/${SERVICE}.d/99-restart.conf" <<'UNIT'
[Unit]
StartLimitIntervalSec=0

[Service]
Restart=always
RestartSec=5
# The bot is more important than a stuck encode when memory runs out.
OOMScoreAdjust=-300
UNIT
systemctl daemon-reload
systemctl restart "${SERVICE}"

echo "== telegram-bot-api working dir (put it into .env as LOCAL_BOT_API_DIR) =="
systemctl cat 'telegram-bot-api*' 2>/dev/null | grep -E 'ExecStart|--dir|-d ' || echo "telegram-bot-api service not found — check how it is started"

echo "== disk =="
df -h /
echo "done"
