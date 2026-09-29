#!/usr/bin/env bash
# Установка бота на сервер Ubuntu (например, DigitalOcean Droplet).
# Запуск:  bash deploy/install.sh   (из папки репозитория, под root)
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$APP_DIR/.env"

echo "==> Устанавливаю Python"
apt-get update -qq
apt-get install -y -qq python3 python3-venv

echo "==> Устанавливаю зависимости"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install -q --upgrade pip
"$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

if [ ! -f "$ENV_FILE" ]; then
  echo
  echo "==> Вставьте ключи (при вставке символы не отображаются — это нормально)"
  read -rsp "TG_TOKEN (токен от @BotFather): " TG_TOKEN; echo
  read -rsp "ANTHROPIC_KEY (ключ Anthropic): " ANTHROPIC_KEY; echo
  umask 077
  printf 'TG_TOKEN=%s\nANTHROPIC_KEY=%s\n' "$TG_TOKEN" "$ANTHROPIC_KEY" > "$ENV_FILE"
fi

echo "==> Настраиваю автозапуск"
cat > /etc/systemd/system/my-bot.service <<UNIT
[Unit]
Description=Telegram bot (Claude)
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$APP_DIR/.venv/bin/python $APP_DIR/bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now my-bot
systemctl restart my-bot
sleep 3
systemctl --no-pager status my-bot | head -n 5
echo
echo "Готово! Напишите боту в Telegram. Логи: journalctl -u my-bot -f"
