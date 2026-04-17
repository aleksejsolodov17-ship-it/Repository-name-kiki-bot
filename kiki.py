import os
import sqlite3
import datetime
import matplotlib.pyplot as plt

from flask import Flask, request
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# =====================
# CONFIG
# =====================
TOKEN = os.getenv("TELEGRAM_TOKEN")  # важно для Render
WEBHOOK_URL = "https://kiki-bot.onrender.com/webhook"

if not TOKEN:
    raise ValueError("TELEGRAM_TOKEN is not set!")

# =====================
# FLASK APP
# =====================
app = Flask(__name__)

# =====================
# TELEGRAM APP
# =====================
application = ApplicationBuilder().token(TOKEN).build()
bot = application.bot

# =====================
# DATABASE
# =====================
conn = sqlite3.connect("kiki.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS results (
    user_id INTEGER,
    score INTEGER,
    date TEXT
)
""")
conn.commit()

def save_result(user_id, score):
    cursor.execute(
        "INSERT INTO results VALUES (?, ?, ?)",
        (user_id, score, str(datetime.date.today()))
    )
    conn.commit()

def get_history(user_id):
    cursor.execute(
        "SELECT score, date FROM results WHERE user_id=?",
        (user_id,)
    )
    return cursor.fetchall()

# =====================
# AI (простая заглушка)
# =====================
def ai(text):
    return f"🌿 KiKi: я тебя слышу\nТы сказал: {text}"

# =====================
# UI
# =====================
keyboard = ReplyKeyboardMarkup(
    [["🧠 Тест", "💬 AI"], ["📊 График", "📈 Статистика"]],
    resize_keyboard=True
)

user_state = {}
chat_mode = set()

questions = [
    "Ты часто устаёшь?",
    "Ты плохо спишь?",
    "Ты переживаешь?",
    "Ты откладываешь дела?",
    "Есть тревога?"
]

# =====================
# HANDLERS
# =====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_mode.discard(update.message.from_user.id)

    await update.message.reply_text(
        "Привет! Я KiKi 🌿",
        reply_markup=keyboard
    )

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id

    # AI MODE
    if user_id in chat_mode:
        await update.message.reply_text(ai(text))
        return

    # START TEST
    if text == "🧠 Тест":
        user_state[user_id] = {"step": 0, "score": 0}
        await update.message.reply_text(questions[0])
        return

    # TEST LOGIC
    if user_id in user_state:
        st = user_state[user_id]

        if text.lower() in ["да", "yes", "ага"]:
            st["score"] += 1

        st["step"] += 1

        if st["step"] < len(questions):
            await update.message.reply_text(questions[st["step"]])
        else:
            score = int((st["score"] / len(questions)) * 100)
            save_result(user_id, score)

            await update.message.reply_text(
                f"📊 Результат: {score}%\nKiKi рядом 🌿",
                reply_markup=keyboard
            )

            del user_state[user_id]
        return

    # AI MODE ENABLE
    if text == "💬 AI":
        chat_mode.add(user_id)
        await update.message.reply_text("AI режим включён 🌿")
        return

    # STATS
    if text == "📈 Статистика":
        data = get_history(user_id)
        if not data:
            await update.message.reply_text("Нет данных 📊")
            return

        avg = sum(x[0] for x in data) / len(data)

        await update.message.reply_text(
            f"Средний стресс: {round(avg,1)}%"
        )
        return

    # GRAPH
    if text == "📊 График":
        data = get_history(user_id)
        if not data:
            await update.message.reply_text("Нет данных 📊")
            return

        values = [x[0] for x in data[-10:]]
        dates = [x[1] for x in data[-10:]]

        plt.figure()
        plt.plot(dates, values, marker="o")
        plt.xticks(rotation=45)
        plt.tight_layout()

        path = f"graph_{user_id}.png"
        plt.savefig(path)
        plt.close()

        await update.message.reply_photo(photo=open(path, "rb"))

        os.remove(path)
        return

    await update.message.reply_text(ai(text))

# =====================
# TELEGRAM WEBHOOK ROUTES
# =====================
application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    update = Update.de_json(data, bot)
    application.process_update(update)
    return "ok"

@app.route("/set_webhook")
def set_webhook():
    try:
        bot.set_webhook(WEBHOOK_URL)
        return "Webhook set OK"
    except Exception as e:
        return str(e)

# =====================
# RUN
# =====================
if __name__ == "__main__":
    print("💎 KiKi v2 FIX RUNNING")
    app.run(host="0.0.0.0", port=5000)
