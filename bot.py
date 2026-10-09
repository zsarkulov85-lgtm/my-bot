"""Telegram-бот, который отвечает на сообщения с помощью Claude.

Ключи берутся из переменных окружения (файл .env на сервере):
    TG_TOKEN       — токен бота от @BotFather
    ANTHROPIC_KEY  — ключ API Anthropic
"""

import asyncio
import datetime as dt
import json
import logging
import os
import re
import time
from collections import defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

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
    "на языке собеседника. Не используй Markdown-разметку. "
    "У тебя есть доступ к интернету: инструмент web_search ищет информацию, "
    "web_fetch открывает страницы по ссылке. Никогда не говори, что у тебя нет "
    "доступа к интернету. Если вопрос касается погоды, новостей, курсов, цен "
    "или чего-то, что могло измениться, обязательно сначала поищи в интернете "
    "и укажи источник."
)
# Поиск и чтение страниц в интернете выполняются на серверах Anthropic.
TOOLS = [
    {"type": "web_search_20260209", "name": "web_search", "max_uses": 5},
    {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 5},
]
MAX_CONTINUATIONS = 5  # сколько раз продолжать долгий поиск (pause_turn)
MAX_HISTORY_MESSAGES = 20  # сколько последних сообщений диалога помнить
TELEGRAM_LIMIT = 4096  # максимальная длина одного сообщения в Telegram

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("my-bot")

def env_key(name: str) -> str:
    """Читает ключ из окружения, убирая пробелы и невидимые символы."""
    return "".join(ch for ch in os.environ[name] if ch.isprintable() and not ch.isspace())


claude = anthropic.AsyncAnthropic(api_key=env_key("ANTHROPIC_KEY"))

# История хранится только текстом (без блоков thinking), поэтому её можно
# свободно обрезать до последних MAX_HISTORY_MESSAGES сообщений.
history: dict[int, list[dict]] = defaultdict(list)


async def run_claude(
    messages: list[dict], system: str, effort: str, tools: list[dict]
) -> tuple[str, str]:
    """Отправляет диалог в Claude, продолжая долгий поиск (pause_turn).

    Возвращает (текст ответа, stop_reason).
    """
    request = list(messages)
    parts: list[str] = []
    paused_blocks: list = []
    for _ in range(MAX_CONTINUATIONS + 1):
        response = await claude.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=system,
            messages=request,
            tools=tools,
            output_config={"effort": effort},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        parts += [b.text for b in response.content if b.type == "text"]
        if response.stop_reason != "pause_turn":
            break
        # Долгий поиск прервался на середине — отправляем ответ обратно,
        # и сервер продолжит с того же места.
        paused_blocks += response.content
        request = list(messages) + [{"role": "assistant", "content": paused_blocks}]
    return "".join(parts).strip(), response.stop_reason


async def ask_claude(chat_id: int, text: str) -> str:
    messages = history[chat_id]
    messages.append({"role": "user", "content": text})
    del messages[:-MAX_HISTORY_MESSAGES]
    # Первое сообщение в истории должно быть от пользователя.
    while messages and messages[0]["role"] != "user":
        messages.pop(0)

    answer, stop_reason = await run_claude(messages, SYSTEM_PROMPT, "low", TOOLS)

    if stop_reason == "refusal":
        messages.pop()  # не сохраняем вопрос, на который не удалось ответить
        return "Извините, на это я ответить не могу."

    if not answer:
        answer = "…"
    messages.append({"role": "assistant", "content": answer})
    return answer


# ---------------------------------------------------------------------------
# Ежедневный поиск новых ЛПУ (лечебно-профилактических учреждений) по РК
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).resolve().parent / "data"
SUBSCRIBERS_FILE = DATA_DIR / "subscribers.json"
SEEN_FILE = DATA_DIR / "seen_lpu.json"
TZ = ZoneInfo("Asia/Almaty")
DIGEST_TIME = os.environ.get("DIGEST_TIME", "09:00")  # время рассылки (Казахстан)
MANUAL_COOLDOWN = 60 * 60  # /lpu можно запускать вручную не чаще раза в час

LPU_TOOLS = [
    {"type": "web_search_20260209", "name": "web_search", "max_uses": 10},
    {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 5},
]
LPU_SYSTEM = (
    "Ты аналитик, который отслеживает рынок здравоохранения Казахстана. "
    "Используй только факты из найденных источников. Никогда не выдумывай "
    "названия, адреса, телефоны и сайты: если данных нет, ставь null."
)
LPU_PROMPT = """Сегодня {today}. Найди в интернете новые лечебно-профилактические
учреждения (ЛПУ) в Казахстане, о которых появилась информация за последние 7 дней:
открытие или ввод в эксплуатацию поликлиник, больниц, врачебных амбулаторий,
ФАПов и медпунктов, частных медцентров и клиник, лабораторий, диагностических
центров, стоматологий; новые медицинские лицензии; объявленные даты открытия.

Ищи на русском и казахском: сайты акиматов и управлений здравоохранения на
gov.kz, inform.kz, kazinform, tengrinews, zakon.kz, kapital.kz, региональные СМИ.
Сделай несколько разных поисков (по стране и по крупным регионам).
Для найденных учреждений по возможности уточни адрес, телефон и сайт.

Ответ дай ТОЛЬКО в виде JSON-массива в блоке ```json, без другого текста.
Каждый элемент:
{{"name": "название", "type": "поликлиника / больница / частный медцентр / ...",
  "region": "область", "city": "город или село", "address": "адрес или null",
  "phone": "телефон или null", "website": "сайт или null",
  "status": "открыто / открывается / строится",
  "date": "дата события или публикации", "source": "ссылка на источник"}}
Если ничего нового не нашлось, верни пустой массив []."""

lpu_lock = asyncio.Lock()
last_manual_run = 0.0


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path: Path, data) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def lpu_key(item: dict) -> str:
    """Ключ для отсева уже присланных учреждений."""
    raw = f"{item.get('name') or ''}|{item.get('city') or item.get('region') or ''}"
    return re.sub(r"[^\w|]", "", raw.lower())


def parse_lpu_json(text: str) -> list[dict]:
    match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.S)
    if match:
        raw = match.group(1)
    else:
        start, end = text.find("["), text.rfind("]")
        if start == -1 or end <= start:
            raise ValueError("в ответе нет JSON-массива")
        raw = text[start : end + 1]
    items = json.loads(raw)
    return [i for i in items if isinstance(i, dict) and i.get("name")]


def format_lpu(items: list[dict], today: str) -> str:
    if not items:
        return f"🏥 Новые ЛПУ в Казахстане — {today}\n\nНовых учреждений не найдено."
    lines = [f"🏥 Новые ЛПУ в Казахстане — {today}", ""]
    for n, i in enumerate(items, 1):
        kind = f" ({i['type']})" if i.get("type") else ""
        lines.append(f"{n}. {i['name']}{kind}")
        place = ", ".join(x for x in (i.get("region"), i.get("city"), i.get("address")) if x)
        if place:
            lines.append(f"📍 {place}")
        if i.get("phone"):
            lines.append(f"📞 {i['phone']}")
        if i.get("website"):
            lines.append(f"🌐 {i['website']}")
        status = " · ".join(x for x in (i.get("status"), i.get("date")) if x)
        if status:
            lines.append(f"🗓 {status}")
        if i.get("source"):
            lines.append(f"🔗 {i['source']}")
        lines.append("")
    lines.append("Данные собраны автоматически — важные контакты перепроверяйте.")
    return "\n".join(lines)


async def find_new_lpu() -> str:
    """Ищет новые ЛПУ и возвращает текст сводки (только ещё не присланные)."""
    today = dt.datetime.now(TZ).strftime("%d.%m.%Y")
    text, stop_reason = await run_claude(
        [{"role": "user", "content": LPU_PROMPT.format(today=today)}],
        LPU_SYSTEM,
        "medium",
        LPU_TOOLS,
    )
    if stop_reason == "refusal":
        raise RuntimeError("Claude отказался выполнять поиск")
    items = parse_lpu_json(text)

    seen: dict[str, str] = load_json(SEEN_FILE, {})
    new_items = []
    for item in items:
        key = lpu_key(item)
        if key and key not in seen:
            seen[key] = today
            new_items.append(item)
    save_json(SEEN_FILE, seen)
    log.info("Поиск ЛПУ: найдено %d, новых %d", len(items), len(new_items))
    return format_lpu(new_items, today)


async def send_long(bot, chat_id: int, text: str) -> None:
    for i in range(0, len(text), TELEGRAM_LIMIT):
        await bot.send_message(chat_id, text[i : i + TELEGRAM_LIMIT],
                               disable_web_page_preview=True)


async def daily_lpu_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    subscribers: list[int] = load_json(SUBSCRIBERS_FILE, [])
    if not subscribers:
        return
    async with lpu_lock:
        try:
            digest = await find_new_lpu()
        except Exception:
            log.exception("Ежедневный поиск ЛПУ не удался")
            digest = "⚠️ Сегодня не получилось выполнить поиск новых ЛПУ. Попробуйте /lpu позже."
    for chat_id in subscribers:
        try:
            await send_long(context.bot, chat_id, digest)
        except Exception:
            log.exception("Не удалось отправить сводку в чат %s", chat_id)


async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    subscribers: list[int] = load_json(SUBSCRIBERS_FILE, [])
    chat_id = update.effective_chat.id
    if chat_id not in subscribers:
        subscribers.append(chat_id)
        save_json(SUBSCRIBERS_FILE, subscribers)
    await update.message.reply_text(
        f"Готово! Каждый день в {DIGEST_TIME} (время Казахстана) я буду присылать "
        "сводку о новых ЛПУ по РК.\n/lpu — найти прямо сейчас\n/unsubscribe — отписаться"
    )


async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    subscribers: list[int] = load_json(SUBSCRIBERS_FILE, [])
    chat_id = update.effective_chat.id
    if chat_id in subscribers:
        subscribers.remove(chat_id)
        save_json(SUBSCRIBERS_FILE, subscribers)
    await update.message.reply_text("Вы отписались от ежедневной сводки о новых ЛПУ.")


async def lpu_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global last_manual_run
    wait = MANUAL_COOLDOWN - (time.monotonic() - last_manual_run)
    if last_manual_run and wait > 0:
        await update.message.reply_text(
            f"Поиск уже запускали недавно. Повторить можно через {int(wait // 60) + 1} мин."
        )
        return
    if lpu_lock.locked():
        await update.message.reply_text("Поиск уже идёт, подождите пару минут.")
        return
    last_manual_run = time.monotonic()
    await update.message.reply_text("🔎 Ищу новые ЛПУ по Казахстану, это займёт 1–3 минуты…")
    async with lpu_lock:
        try:
            digest = await find_new_lpu()
        except Exception:
            log.exception("Ручной поиск ЛПУ не удался")
            digest = "⚠️ Не получилось выполнить поиск. Попробуйте позже."
    await send_long(context.bot, update.effective_chat.id, digest)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Привет! Я бот на базе Claude. Напишите мне что-нибудь.\n"
        "/reset — начать разговор заново\n"
        "/subscribe — ежедневная сводка о новых ЛПУ по РК\n"
        "/lpu — найти новые ЛПУ прямо сейчас\n"
        "/unsubscribe — отписаться от сводки"
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
    app = Application.builder().token(env_key("TG_TOKEN")).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("subscribe", subscribe))
    app.add_handler(CommandHandler("unsubscribe", unsubscribe))
    app.add_handler(CommandHandler("lpu", lpu_now))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    hour, minute = map(int, DIGEST_TIME.split(":"))
    app.job_queue.run_daily(
        daily_lpu_job, dt.time(hour, minute, tzinfo=TZ), name="daily_lpu"
    )
    log.info("Бот запущен, сводка ЛПУ ежедневно в %s (Asia/Almaty)", DIGEST_TIME)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
