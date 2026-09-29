"""Telegram-бот, который отвечает на сообщения с помощью Claude.

Ключи берутся из переменных окружения (файл .env на сервере):
    TG_TOKEN       — токен бота от @BotFather
    ANTHROPIC_KEY  — ключ API Anthropic
"""

import logging
import os
from collections import defaultdict

import anthropic
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

MODEL = "claude-opus-5-5"
SYSTEM_PROMPT = (
    "Ты дружелюбный помощник в Telegram. Отвечай кратко и по делу, "
    "на языке собеседника. Не используй Markdown-разметку."
)
MAX_HISTORY_MESSAGES = 20  # сколько последних сообщений диалога помнить
TELEGRAM_LIMIT = 4096  # максимальная длина одного сообщения в Telegram

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("my-bot")

claude = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_KEY"])

# История хранится только текстом (без блоков thinking), поэтому её можно
# свободно обрезать до последних MAX_HISTORY_MESSAGES сообщений.
history: dict[int, list[dict]] = defaultdict(list)


async def ask_claude(chat_id: int, text: str) -> str:
    messages = history[chat_id]
    messages.append({"role": "user", "content": text})
    del messages[:-MAX_HISTORY_MESSAGES]
    # Первое сообщение в истории должно быть от пользователя.
    while messages and messages[0]["role"] != "user":
        messages.pop(0)

    response = await claude.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=messages,
        output_config={"effort": "low"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )

    if response.stop_reason == "refusal":
        messages.pop()  # не сохраняем вопрос, на который не удалось ответить
        return "Извините, на это я ответить не могу."

    answer = "".join(b.text for b in response.content if b.type == "text").strip()
    if not answer:
        answer = "…"
    messages.append({"role": "assistant", "content": answer})
    return answer


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Привет! Я бот на базе Claude. Напишите мне что-нибудь.\n"
        "/reset — начать разговор заново."
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    history.pop(update.effective_chat.id, None)
    await update.message.reply_text("Начинаем заново.")


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id, ChatAction.TYPING)
    try:
        answer = await ask_claude(chat_id, update.message.text)
    except anthropic.RateLimitError:
        history[chat_id].pop()
        answer = "Слишком много запросов, попробуйте через минуту."
    except anthropic.AuthenticationError:
        log.error("Неверный ANTHROPIC_KEY")
        history[chat_id].pop()
        answer = "Ошибка настройки бота: неверный ключ Anthropic."
    except (anthropic.APIStatusError, anthropic.APIConnectionError):
        log.exception("Ошибка запроса к Claude")
        history[chat_id].pop()
        answer = "Не получилось получить ответ, попробуйте ещё раз."

    for i in range(0, len(answer), TELEGRAM_LIMIT):
        await update.message.reply_text(answer[i : i + TELEGRAM_LIMIT])


def main() -> None:
    app = Application.builder().token(os.environ["TG_TOKEN"]).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    log.info("Бот запущен")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
