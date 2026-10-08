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
  # Убираем невидимые символы (например, от Ctrl+V) и пробелы по краям.
  clean() { printf '%s' "$1" | tr -cd '[:graph:]'; }
  TG_TOKEN=""; ANTHROPIC_KEY=""
  while :; do
    read -rsp ">>> Вставьте TG_TOKEN (токен от @BotFather) и нажмите Enter: " TG_TOKEN; echo
    TG_TOKEN="$(clean "$TG_TOKEN")"
    if [[ "$TG_TOKEN" =~ ^[0-9]+:[A-Za-z0-9_-]{30,}$ ]]; then
      echo "    принято (начинается на ${TG_TOKEN:0:6}..., длина ${#TG_TOKEN})"; break
    fi
    echo "    Это не похоже на токен Telegram (вид: 123456789:AAH...). Попробуйте ещё раз."
    echo "    Вставляйте правой кнопкой мыши -> Paste или Ctrl+Shift+V (не Ctrl+V)."
  done
  while :; do
    read -rsp ">>> Вставьте ANTHROPIC_KEY (ключ Anthropic) и нажмите Enter: " ANTHROPIC_KEY; echo
    ANTHROPIC_KEY="$(clean "$ANTHROPIC_KEY")"
    if [[ "$ANTHROPIC_KEY" =~ ^sk-ant-[A-Za-z0-9_-]{20,}$ ]]; then
      echo "    принято (начинается на ${ANTHROPIC_KEY:0:10}..., длина ${#ANTHROPIC_KEY})"; break
    fi
    echo "    Это не похоже на ключ Anthropic (вид: sk-ant-...). Попробуйте ещё раз."
    echo "    Вставляйте правой кнопкой мыши -> Paste или Ctrl+Shift+V (не Ctrl+V)."
  done
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
