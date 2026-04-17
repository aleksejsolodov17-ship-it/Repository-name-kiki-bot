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

# Проверка наличия ключей
if not TOKEN or not WEBHOOK_URL:
    print("❌ ОШИБКА: TELEGRAM_TOKEN или WEBHOOK_URL не установлены в Environment Variables!")

bot = Bot(token=TOKEN)
app = Flask(__name__)

# =========================
# 📊 БАЗА ДАННЫХ
# =========================
def get_db():
    conn = sqlite3.connect("kiki.db", check_same_thread=False)
    return conn

# Инициализация базы данных
with get_db() as conn:
    conn.execute("""
    CREATE TABLE IF NOT EXISTS results (
        user_id INTEGER,
        score INTEGER,
        date TEXT
    )
    """)

def save_result(user_id, score):
    with get_db() as conn:
        conn.execute("INSERT INTO results VALUES (?, ?, ?)",
                     (user_id, score, str(datetime.date.today())))

def get_history(user_id):
    with get_db() as conn:
        cursor = conn.execute("SELECT score, date FROM results WHERE user_id=? ORDER BY rowid DESC LIMIT 10", (user_id,))
        return cursor.fetchall()

# =========================
# 🎮 ЛОГИКА БОТА
# =========================
keyboard = ReplyKeyboardMarkup(
    [["🧠 Тест", "💬 AI"], ["📊 График", "📈 Статистика"]],
    resize_keyboard=True
)

questions = [
    "Ты часто устаёшь?",
    "Ты плохо спишь?",
    "Ты много переживаешь?",
    "Ты откладываешь дела на потом?",
    "Чувствуешь ли ты тревогу?"
]

user_state = {}
ai_mode = set()

async def process_update(update: Update):
    if not update.message or not update.message.text:
        return

    text = update.message.text
    user_id = update.message.from_user.id

    # Команда /start
    if text == "/start":
        ai_mode.discard(user_id)
        user_state.pop(user_id, None)
        await bot.send_message(chat_id=user_id, text="Привет! Я KiKi 🌿 Твой AI-помощник.", reply_markup=keyboard)
        return

    # Режим AI
    if user_id in ai_mode and text != "❌ Выход":
        await bot.send_message(chat_id=user_id, text=f"KiKi 🌿: Я услышала тебя. Ты написал: '{text}'")
        return

    # Логика теста
    if text == "🧠 Тест":
        user_state[user_id] = {"step": 0, "score": 0}
        await bot.send_message(chat_id=user_id, text=questions[0])
        return

    if user_id in user_state:
        st = user_state[user_id]
        if text.lower() in ["да", "yes", "ага", "д"]:
            st["score"] += 1
        st["step"] += 1

        if st["step"] < len(questions):
            await bot.send_message(chat_id=user_id, text=questions[st["step"]])
        else:
            score = int((st["score"] / len(questions)) * 100)
            save_result(user_id, score)
            await bot.send_message(chat_id=user_id, text=f"📊 Результат: {score}%\nKiKi рядом. 🌿", reply_markup=keyboard)
            del user_state[user_id]
        return

    # Кнопки меню
    if text == "💬 AI":
        ai_mode.add(user_id)
        await bot.send_message(chat_id=user_id, text="AI режим включён. Расскажи, что у тебя на душе? (Выход — /start)")
    
    elif text == "📈 Статистика":
        data = get_history(user_id)
        if not data:
            await bot.send_message(chat_id=user_id, text="Статистики пока нет.")
        else:
            avg = sum(x[0] for x in data) / len(data)
            await bot.send_message(chat_id=user_id, text=f"Твой средний уровень стресса: {round(avg, 1)}%")

    elif text == "📊 График":
        data = get_history(user_id)
        if len(data) < 2:
            await bot.send_message(chat_id=user_id, text="Нужно пройти тест хотя бы 2 раза.")
            return

        scores = [x[0] for x in data][::-1]
        dates = [x[1] for x in data][::-1]
        
        plt.figure(figsize=(8, 4))
        plt.plot(dates, scores, marker='o', color='green')
        plt.title("Твой прогресс")
        plt.xticks(rotation=45)
        plt.tight_layout()
        
        path = f"graph_{user_id}.png"
        plt.savefig(path)
        plt.close()
        
        with open(path, "rb") as photo:
            await bot.send_photo(chat_id=user_id, photo=photo)
        os.remove(path)

# =========================
# 🌐 ROUTES (Flask)
# =========================
@app.route("/webhook", methods=["POST"])
async def webhook():
    # Асинхронно обрабатываем входящее сообщение
    update = Update.de_json(request.get_json(force=True), bot)
    await process_update(update)
    return "ok"

@app.route("/set_webhook")
async def set_webhook():
    try:
        # Прямой вызов асинхронных методов бота
        await bot.delete_webhook()
        # Важно: добавляем /webhook в конец URL
        success = await bot.set_webhook(url=f"{WEBHOOK_URL}/webhook")
        if success:
            return jsonify({"ok": True, "message": "Webhook set successfully!"})
        return jsonify({"ok": False, "message": "Failed to set webhook."})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/")
def home():
    return "KiKi is alive 💎"

# =========================
# ▶️ ЗАПУСК
# =========================
if __name__ == "__main__":
    # Render сам подставит нужный PORT
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
