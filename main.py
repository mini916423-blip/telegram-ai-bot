import os
import asyncio
from collections import defaultdict, deque

from fastapi import FastAPI, Request
from openai import AsyncOpenAI
from telegram import Update
from telegram.ext import Application, MessageHandler, ContextTypes, filters

BOT_TOKEN = os.environ["BOT_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
WEBHOOK_URL = os.environ["WEBHOOK_URL"].rstrip("/")

client = AsyncOpenAI(api_key=OPENAI_API_KEY)

SYSTEM_PROMPT = """
Tum Telegram group ki ek friendly female AI member ho.

Hindi/Hinglish me natural aur casual baat karo.
Feminine wording use karo, jaise "karungi", "bataungi", "samajh gayi".

Friendly, cute aur confident personality rakho.
Group ke sabhi members se respectfully baat karo.
User ki baat ka relevant aur natural jawab do.
Zyada formal ya robotic mat lagna.

Replies short aur human-like rakho, usually 1-4 lines.
Agar message sirf emoji, spam ya bilkul irrelevant ho,
to [NO_REPLY] likh sakti ho.

Agar koi directly puche ki tum AI/bot ho, to sach batao.
Kisi user ki personal information guess mat karo.
"""

history = defaultdict(lambda: deque(maxlen=12))
locks = defaultdict(asyncio.Lock)

bot_app = (
    Application.builder()
    .token(BOT_TOKEN)
    .updater(None)
    .build()
)


async def generate_reply(chat_id, username, text):
    async with locks[chat_id]:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]

        for role, content in history[chat_id]:
            messages.append({
                "role": role,
                "content": content
            })

        messages.append({
            "role": "user",
            "content": f"{username}: {text}"
        })

        response = await client.responses.create(
            model="gpt-5-mini",
            input=messages,
            max_output_tokens=180
        )

        answer = (response.output_text or "").strip()

        history[chat_id].append(
            ("user", f"{username}: {text}")
        )

        if not answer or answer == "[NO_REPLY]":
            return ""

        history[chat_id].append(
            ("assistant", answer)
        )

        return answer


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    if update.message.from_user and update.message.from_user.is_bot:
        return

    user = update.effective_user
    chat = update.effective_chat

    if not user or not chat:
        return

    username = user.first_name or "User"
    text = update.message.text.strip()

    try:
        answer = await generate_reply(
            chat.id,
            username,
            text
        )

        if answer:
            await update.message.reply_text(answer)

    except Exception as e:
        print("ERROR:", repr(e))


bot_app.add_handler(
    MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        on_message
    )
)

web_app = FastAPI()


@web_app.on_event("startup")
async def startup():
    await bot_app.initialize()
    await bot_app.start()

    await bot_app.bot.set_webhook(
        url=f"{WEBHOOK_URL}/telegram",
        allowed_updates=Update.ALL_TYPES
    )

    print("Bot is running...")


@web_app.on_event("shutdown")
async def shutdown():
    await bot_app.bot.delete_webhook()
    await bot_app.stop()
    await bot_app.shutdown()


@web_app.get("/")
async def home():
    return {"status": "Bot is running"}


@web_app.post("/telegram")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, bot_app.bot)
    await bot_app.update_queue.put(update)
    return {"ok": True}
