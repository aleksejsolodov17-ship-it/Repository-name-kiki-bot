import os
import sqlite3
import datetime
import asyncio
import matplotlib.pyplot as plt
from flask import Flask, request, jsonify
from telegram import Bot, Update, ReplyKeyboardMarkup

# =========================
# 🔑 CONFIG (берёт из Render)
# =========================
TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

# Инициализация бота
bot = Bot(token=TOKEN)
app = Flask(__name__)

# =========================
# 📊 DATABASE
# =========================
def get_db_connection():
    conn = sqlite3.connect("kiki.db", check_same_thread=False)
    return conn

# Создание таблиц при запуске
conn = get_db_connection()
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
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO results VALUES (?, ?, ?)",
                   (user_id, score, str(datetime.date.today())))
    conn.commit()

def get_history(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT score, date FROM results WHERE user_id=?", (user_id,))
    return cursor.fetchall()

# =========================
# 🧠 ДАННЫЕ И ЛОГИКА
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
    "Ты много переживаешь?",
    "Ты откладываешь дела на потом?",
    "Чувствуешь ли ты тревогу?"
]

# Асинхронная отправка сообщений
async def send_reply(chat_id, text, reply_markup=None):
    await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)

# Основной обработчик логики
async def process_update(update: Update):
    if not update.message or not update.message.text:
        return

    text = update.message.text
    user_id = update.message.from_user.id

    # Команда /start
    if text == "/start":
        ai_mode.discard(user_id)
        user_state.pop(user_id, None)
        await send_reply(user_id, "Привет! Я KiKi 🌿 Выбери действие:", keyboard)
        return

    # Режим AI
    if user_id in ai_mode and text != "❌ Выход":
        await send_reply(user_id, f"KiKi 🌿: Я тебя слышу. Ты сказал: '{text}'")
        return

    # Логика теста
    if text == "🧠 Тест":
        user_state[user_id] = {"step": 0, "score": 0}
        await send_reply(user_id, questions[0])
        return

    if user_id in user_state:
        st = user_state[user_id]
        if text.lower() in ["да", "yes", "ага"]:
            st["score"] += 1
        st["step"] += 1

        if st["step"] < len(questions):
            await send_reply(user_id, questions[st["step"]])
        else:
            score = int((st["score"] / len(questions)) * 100)
            save_result(user_id, score)
            await send_reply(user_id, f"📊 Твой результат: {score}%\nKiKi всегда рядом 🌿", keyboard)
            del user_state[user_id]
        return

    # Кнопки меню
    if text == "💬 AI":
        ai_mode.add(user_id)
        await send_reply(user_id, "Режим AI включён. Напиши мне что-нибудь! (Для выхода нажми /start)")
    
    elif text == "📈 Статистика":
        data = get_history(user_id)
        if not data:
            await send_reply(user_id, "Данных пока нет. Пройди тест!")
        else:
            avg = sum(x[0] for x in data) / len(data)
            await send_reply(user_id, f"Твой средний уровень стресса: {round(avg, 1)}%")

    elif text == "📊 График":
        data = get_history(user_id)
        if len(data) < 2:
            await send_reply(user_id, "Нужно пройти тест хотя бы 2 раза для графика.")
            return

        values = [x[0] for x in data[-10:]]
        dates = [x[1] for x in data[-10:]]
        plt.figure()
        plt.plot(dates, values, marker="o", color="green")
        plt.title("Динамика стресса")
        plt.xticks(rotation=45)
        plt.tight_layout()
        
        path = f"graph_{user_id}.png"
        plt.savefig(path)
        plt.close()
        
        with open(path, "rb") as photo:
            await bot.send_photo(chat_id=user_id, photo=photo)
        os.remove(path)

# =========================
# 🌐 FLASK ROUTES (Webhook)
# =========================
@app.route("/webhook", methods=["POST"])
def webhook():
    if request.method == "POST":
        data = request.get_json(force=True)
        update = Update.de_json(data, bot)
        # Запускаем асинхронную логику
        asyncio.run(process_update(update))
        return "ok"
    return "error"

@app.route("/set_webhook")
def set_webhook():
    # Исправленная асинхронная установка вебхука
    async def setup():
        await bot.delete_webhook()
        return await bot.set_webhook(url=f"{WEBHOOK_URL}/webhook")
    
    result = asyncio.run(setup())
    return jsonify({"ok": True, "result": str(result)})

@app.route("/")
def home():
    return "KiKi is alive 💎"

# =========================
# ▶️ RUN
# =========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
