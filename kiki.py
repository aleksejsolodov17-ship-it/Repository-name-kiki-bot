import os
import sqlite3
import datetime
import matplotlib.pyplot as plt

from flask import Flask, request, jsonify
from telegram import Bot, Update, ReplyKeyboardMarkup

# =========================
# CONFIG
# =========================
TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

if not TOKEN:
    raise Exception("TELEGRAM_TOKEN is missing")

bot = Bot(token=TOKEN)

app = Flask(__name__)

# =========================
# DATABASE
# =========================
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
    cursor.execute("SELECT score, date FROM results WHERE user_id=?", (user_id,))
    return cursor.fetchall()


# =========================
# AI (stub)
# =========================
def ai(text):
    return f"KiKi 🌿: {text}"


# =========================
# UI
# =========================
keyboard = ReplyKeyboardMarkup(
    [["🧠 Тест", "💬 AI"], ["📊 График", "📈 Статистика"]],
    resize_keyboard=True
)

user_state = {}
ai_mode = set()

questions = [
    "Ты часто устаёшь?",
    "Ты плохо спишь?",
    "Ты переживаешь?",
    "Ты откладываешь дела?",
    "Есть тревога?"
]


# =========================
# TELEGRAM HANDLER CORE
# =========================
def handle_message(update: Update):
    text = update.message.text
    user_id = update.message.from_user.id

    # AI MODE
    if user_id in ai_mode:
        update.message.reply_text(ai(text))
        return

    # START TEST
    if text == "🧠 Тест":
        user_state[user_id] = {"step": 0, "score": 0}
        update.message.reply_text(questions[0])
        return

    # TEST FLOW
    if user_id in user_state:
        st = user_state[user_id]

        if text.lower() in ["да", "yes"]:
            st["score"] += 1

        st["step"] += 1

        if st["step"] < len(questions):
            update.message.reply_text(questions[st["step"]])
        else:
            score = int((st["score"] / len(questions)) * 100)

            save_result(user_id, score)

            update.message.reply_text(
                f"📊 Результат: {score}%\nKiKi рядом 🌿",
                reply_markup=keyboard
            )

            del user_state[user_id]
        return

    # AI MODE ENABLE
    if text == "💬 AI":
        ai_mode.add(user_id)
        update.message.reply_text("AI режим включён 🌿")
        return

    # STATS
    if text == "📈 Статистика":
        data = get_history(user_id)
        if not data:
            update.message.reply_text("Нет данных 📊")
            return

        avg = sum(x[0] for x in data) / len(data)
        update.message.reply_text(f"Средний уровень: {round(avg,1)}%")
        return

    # GRAPH
    if text == "📊 График":
        data = get_history(user_id)
        if not data:
            update.message.reply_text("Нет данных 📊")
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

        update.message.reply_photo(photo=open(path, "rb"))
        os.remove(path)
        return

    update.message.reply_text(ai(text))


# =========================
# WEBHOOK ROUTE
# =========================
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    update = Update.de_json(data, bot)
    handle_message(update)
    return "ok"


# =========================
# SET WEBHOOK
# =========================
@app.route("/set_webhook")
def set_webhook():
    try:
        bot.delete_webhook()
        result = bot.set_webhook(url=WEBHOOK_URL)
        return jsonify({"ok": True, "result": str(result)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# =========================
# HOME (Render health check)
# =========================
@app.route("/")
def home():
    return "KiKi is alive 💎"


# =========================
# RUN
# =========================
if __name__ == "__main__":
    print("💎 KiKi v3 PRODUCTION RUNNING")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
