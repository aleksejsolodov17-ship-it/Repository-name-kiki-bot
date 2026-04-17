import os
import sqlite3
import datetime
import asyncio
import matplotlib.pyplot as plt
from flask import Flask, request, jsonify
from telegram import Bot, Update, ReplyKeyboardMarkup

# =========================
# 🔑 КОНФИГУРАЦИЯ
# =========================
TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

bot = Bot(token=TOKEN)
app = Flask(__name__)

# =========================
# 📊 БАЗА ДАННЫХ
# =========================
def get_db():
    conn = sqlite3.connect("kiki.db", check_same_thread=False)
    return conn

with get_db() as conn:
    conn.execute("CREATE TABLE IF NOT EXISTS results (user_id INTEGER, score INTEGER, date TEXT)")

def save_result(user_id, score):
    with get_db() as conn:
        conn.execute("INSERT INTO results VALUES (?, ?, ?)", (user_id, score, str(datetime.date.today())))

def get_history(user_id):
    with get_db() as conn:
        return conn.execute("SELECT score, date FROM results WHERE user_id=? ORDER BY rowid DESC LIMIT 10", (user_id,)).fetchall()

# =========================
# 🎮 ЛОГИКА БОТА
# =========================
keyboard = ReplyKeyboardMarkup([["🧠 Тест", "💬 AI"], ["📊 График", "📈 Статистика"]], resize_keyboard=True)
questions = ["Ты часто устаёшь?", "Ты плохо спишь?", "Ты много переживаешь?", "Ты откладываешь дела?", "Чувствуешь тревогу?"]
user_state, ai_mode = {}, set()

async def process_update(update: Update):
    if not update.message or not update.message.text: return
    text, user_id = update.message.text, update.message.from_user.id

    if text == "/start":
        ai_mode.discard(user_id)
        user_state.pop(user_id, None)
        await bot.send_message(chat_id=user_id, text="Привет! Я KiKi 🌿 Чем помогу?", reply_markup=keyboard)
    elif text == "🧠 Тест":
        user_state[user_id] = {"step": 0, "score": 0}
        await bot.send_message(chat_id=user_id, text=questions[0])
    elif user_id in user_state:
        st = user_state[user_id]
        if text.lower() in ["да", "yes", "ага", "д"]: st["score"] += 1
        st["step"] += 1
        if st["step"] < len(questions):
            await bot.send_message(chat_id=user_id, text=questions[st["step"]])
        else:
            score = int((st["score"] / len(questions)) * 100)
            save_result(user_id, score)
            await bot.send_message(chat_id=user_id, text=f"📊 Результат: {score}%\nKiKi рядом 🌿", reply_markup=keyboard)
            del user_state[user_id]
    elif text == "💬 AI":
        ai_mode.add(user_id)
        await bot.send_message(chat_id=user_id, text="AI режим включён! (Выход — /start)")
    elif user_id in ai_mode:
        await bot.send_message(chat_id=user_id, text=f"KiKi 🌿: Я тебя слышу. Ты написал: '{text}'")

# =========================
# 🌐 ROUTES (Webhook)
# =========================
@app.route("/webhook", methods=["POST"])
def webhook():
    # Используем новый поток для асинхронной обработки, чтобы не вешать Flask
    update = Update.de_json(request.get_json(force=True), bot)
    asyncio.run(process_update(update))
    return "ok"

@app.route("/set_webhook")
def set_webhook():
    try:
        # Самый простой способ регистрации через asyncio.run
        asyncio.run(bot.delete_webhook())
        success = asyncio.run(bot.set_webhook(url=f"{WEBHOOK_URL}/webhook"))
        if success:
            return "✅ Webhook установлен! Пиши боту в Telegram."
        return "❌ Ошибка при установке."
    except Exception as e:
        return f"⚠ Ошибка: {str(e)}"

@app.route("/")
def home():
    return "KiKi is alive 💎"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
