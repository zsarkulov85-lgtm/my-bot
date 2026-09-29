# my-bot

Telegram-бот, который отвечает на сообщения с помощью Claude (модель `claude-opus-5-5`).

Команды бота: `/start` — приветствие, `/reset` — начать разговор заново.

## Установка на сервер (DigitalOcean, Ubuntu)

Подключитесь к серверу (в панели DigitalOcean: Droplet → **Console**) и выполните:

```bash
git clone -b claude/focused-tesla-hvjs0z https://github.com/zsarkulov85-lgtm/my-bot.git /opt/my-bot && bash /opt/my-bot/deploy/install.sh
```

Скрипт спросит `TG_TOKEN` и `ANTHROPIC_KEY` и сохранит их в `/opt/my-bot/.env`
(этот файл не попадает в git). Бот запускается как служба и перезапускается сам.

Полезные команды:

```bash
journalctl -u my-bot -f           # логи
systemctl restart my-bot          # перезапуск
nano /opt/my-bot/.env             # поменять ключи (потом перезапуск)
cd /opt/my-bot && git pull && systemctl restart my-bot   # обновить код
```
