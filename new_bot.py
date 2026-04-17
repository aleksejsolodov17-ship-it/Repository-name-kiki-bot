import os
import sqlite3
import datetime
import matplotlib.pyplot as plt

from flask import Flask, request
from telegram import Update, Bot, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# =====================
# CONFIG
# =====================
TOKEN = "8786833012:AAG1uQ_lOtu0cNvo4xejFgLpQDC7OloCJSo"
WEBHOOK_URL = "https://your-domain.com/webhook"

bot = Bot(token=TOKEN)

app = Flask("KiKi")

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
    cursor.execute("INSERT INTO results VALUES (?, ?, ?)",
                   (user_id, score, str(datetime.date.today())))
    conn.commit()

def get_history(user_id):
    cursor.execute("SELECT score, date FROM results WHERE user_id=?", (user_id,))
    return cursor.fetchall()

# =====================
# AI (safe fallback)
# =====================
def ai(text):
    return f"KiKi рядом 🌿\nТы сказал: {text}"

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
# START
# =====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_mode.discard(update.message.from_user.id)

    await update.message.reply_text(
        "Привет! Я KiKi 🌿",
        reply_markup=keyboard
    )

# =====================
# HANDLER
# =====================
async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id

    # AI CHAT MODE
    if user_id in chat_mode:
        await update.message.reply_text(ai(text))
        return

    # TEST START
    if text == "🧠 Тест":
        user_state[user_id] = {"step": 0, "score": 0}
        await update.message.reply_text(questions[0])
        return

    # TEST LOGIC
    if user_id in user_state:
        st = user_state[user_id]

        if text.lower() in ["да", "yes"]:
            st["score"] += 1

        st["step"] += 1

        if st["step"] < len(questions):
            await update.message.reply_text(questions[st["step"]])
        else:
            score = int((st["score"] / len(questions)) * 100)
            save_result(user_id, score)

            await update.message.reply_text(
                f"📊 Результат: {score}%\nKiKi с тобой 🌿",
                reply_markup=keyboard
            )

            del user_state[user_id]
        return

    # AI MODE
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
        await update.message.reply_text(f"Средний стресс: {round(avg,1)}%")
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
# APP
# =====================
app_bot = ApplicationBuilder().token(TOKEN).build()

app_bot.add_handler(CommandHandler("start", start))
app_bot.add_handler(MessageHandler(filters.TEXT, handle))

# =====================
# FLASK WEBHOOK
# =====================
@app.route("/webhook", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), app_bot.bot)
    app_bot.update_queue.put_nowait(update)
    return "ok"

@app.route("/set_webhook")
def set_webhook():
    app_bot.bot.set_webhook(WEBHOOK_URL)
    return "OK"

# =====================
# RUN
# =====================
if __name__ == "__main__":
    print("💎 KiKi v2 FIXED RUNNING")
    app.run(host="0.0.0.0", port=5000)