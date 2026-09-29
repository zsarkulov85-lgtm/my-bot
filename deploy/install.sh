#!/usr/bin/env bash
# Установка бота на сервер Ubuntu (например, DigitalOcean Droplet).
# Запуск:  bash deploy/install.sh   (из папки репозитория, под root)
set -euo pipefail
trap 'echo; echo "ОШИБКА: установка остановилась. Пришлите строки выше (без ключей)."' ERR

if [ "$(id -u)" -ne 0 ]; then
  echo "Запустите через sudo: sudo bash $0"; exit 1
fi

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$APP_DIR/.env"

echo "==> Устанавливаю Python"
# На новом сервере в фоне могут идти обновления — ждём, пока они закончатся.
APT="apt-get -o DPkg::Lock::Timeout=600"
$APT update
DEBIAN_FRONTEND=noninteractive $APT install -y python3 python3-venv

echo "==> Устанавливаю зависимости"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install -q --upgrade pip
"$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

if [ ! -f "$ENV_FILE" ]; then
  echo
  echo "==> Вставьте ключи (при вставке символы не отображаются — это нормально)"
  TG_TOKEN=""; ANTHROPIC_KEY=""
  while [ -z "$TG_TOKEN" ]; do
    read -rsp ">>> Вставьте TG_TOKEN (токен от @BotFather) и нажмите Enter: " TG_TOKEN; echo
  done
  echo "    принято"
  while [ -z "$ANTHROPIC_KEY" ]; do
    read -rsp ">>> Вставьте ANTHROPIC_KEY (ключ Anthropic) и нажмите Enter: " ANTHROPIC_KEY; echo
  done
  echo "    принято"
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
