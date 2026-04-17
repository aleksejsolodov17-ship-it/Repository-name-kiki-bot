import os
import sqlite3
import datetime
import asyncio
import matplotlib.pyplot as plt
from flask import Flask, request, jsonify
from telegram import Bot, Update, ReplyKeyboardMarkup
from gigachat import GigaChat

# =========================
# 🔑 КОНФИГУРАЦИЯ
# =========================
TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
GIGA_KEY = os.getenv("GIGACHAT_CREDENTIALS")

bot = Bot(token=TOKEN)
app = Flask(__name__)

# =========================
# 🧠 МОЗГ GIGACHAT (РФ)
# =========================
def ask_ai(text):
    if not GIGA_KEY:
        return "KiKi 🌿: Я тебя слышу! (GigaChat не настроен в Environment)"
    
    try:
        # Авторизация и запрос к Сберу
        # verify_ssl_certs=False нужен для работы на некоторых серверах без сертификатов Сбера
        with GigaChat(credentials=GIGA_KEY, verify_ssl_certs=False) as giga:
            response = giga.chat({
                "messages": [
                    {"role": "system", "content": "Ты KiKi — добрый ИИ-психолог для подростков. Отвечай тепло, коротко и только на русском языке. Поддерживай и давай советы против стресса."},
                    {"role": "user", "content": text}
                ]
            })
            return response.choices[0].message.content
    except Exception as e:
        print(f"Ошибка GigaChat: {e}")
        return "KiKi 🌿: У меня возникла небольшая техническая заминка, но я всё равно рядом! Попробуй написать еще раз?"

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
        cursor = conn.execute("SELECT score, date FROM results WHERE user_id=? ORDER BY rowid DESC", (user_id,))
        return [row[0] for row in cursor.fetchall()]

# =========================
# 🎮 ЛОГИКА БОТА
# =========================
keyboard = ReplyKeyboardMarkup([["🧠 Тест", "💬 AI"], ["📊 График", "📈 Статистика"]], resize_keyboard=True)
questions = ["Ты часто устаёшь?", "Ты плохо спишь?", "Ты много переживаешь?", "Ты откладываешь дела?", "Чувствуешь тревогу?"]

user_state = {}
ai_mode = set()

async def process_update(update: Update):
    if not update.message or not update.message.text: return
    text, user_id = update.message.text, update.message.from_user.id

    # 1. КОМАНДЫ
    if text == "/start":
        ai_mode.discard(user_id)
        user_state.pop(user_id, None)
        await bot.send_message(chat_id=user_id, text="Привет! Я KiKi 🌿 Твой AI-помощник против стресса. Выбери действие:", reply_markup=keyboard)
        return

    # 2. ТЕСТ
    if text == "🧠 Тест":
        ai_mode.discard(user_id)
        user_state[user_id] = {"step": 0, "score": 0}
        await bot.send_message(chat_id=user_id, text=questions[0], reply_markup=ReplyKeyboardMarkup([["Да", "Нет"]], resize_keyboard=True))
        return

    if user_id in user_state:
        st = user_state[user_id]
        if text.lower() in ["да", "yes", "ага", "д"]: st["score"] += 1
        st["step"] += 1

        if st["step"] < len(questions):
            await bot.send_message(chat_id=user_id, text=questions[st["step"]])
        else:
            score = min(int((st["score"] / len(questions)) * 100), 100)
            save_result(user_id, score)
            await bot.send_message(chat_id=user_id, text=f"📊 Твой результат: {score}%\nKiKi рядом. Мы можем обсудить это в ИИ-чате! 🌿", reply_markup=keyboard)
            user_state.pop(user_id, None)
        return

    # 3. СТАТИСТИКА И ГРАФИК
    if text == "📈 Статистика":
        data = get_history(user_id)
        if not data:
            await bot.send_message(chat_id=user_id, text="Данных пока нет 📊")
        else:
            avg = sum(data) / len(data)
            await bot.send_message(chat_id=user_id, text=f"Твой средний уровень стресса: {round(avg, 1)}% 🌿")
        return

    if text == "📊 График":
        with get_db() as conn:
            data = conn.execute("SELECT score, date FROM results WHERE user_id=? ORDER BY rowid DESC LIMIT 10", (user_id,)).fetchall()
        
        if len(data) < 2:
            await bot.send_message(chat_id=user_id, text="Нужно хотя бы 2 результата для графика 📈")
            return
        
        scores = [x[0] for x in data][::-1]
        dates = [x[1] for x in data][::-1]
        
        plt.figure(figsize=(8, 4))
        plt.plot(dates, scores, marker='o', color='#4CAF50', linewidth=2)
        plt.title("Динамика твоего состояния")
        plt.ylim(0, 105)
        plt.xticks(rotation=45)
        plt.tight_layout()
        
        path = f"graph_{user_id}.png"
        plt.savefig(path)
        plt.close()
        
        with open(path, "rb") as photo:
            await bot.send_photo(chat_id=user_id, photo=photo)
        os.remove(path)
        return

    # 4. AI ЧАТ
    if text == "💬 AI":
        ai_mode.add(user_id)
        await bot.send_message(chat_id=user_id, text="Режим AI включён! Расскажи, что тебя беспокоит? 🌿 (Выход — /start)")
        return

    if user_id in ai_mode:
        await bot.send_chat_action(chat_id=user_id, action="typing")
        answer = ask_ai(text)
        await bot.send_message(chat_id=user_id, text=answer)
        return

# =========================
# 🌐 ROUTES (Flask + Webhook)
# =========================
@app.route("/webhook", methods=["POST"])
async def webhook():
    data = request.get_json(force=True)
    update = Update.de_json(data, bot)
    await process_update(update)
    return "ok"

@app.route("/")
def home():
    return "KiKi is alive and smart 💎"

# =========================
# ▶️ ЗАПУСК
# =========================
if __name__ == "__main__":
    async def on_startup():
        try:
            await bot.delete_webhook()
            await bot.set_webhook(url=f"{WEBHOOK_URL}/webhook")
            print("✅ Webhook установлен автоматически!")
        except Exception as e:
            print(f"❌ Ошибка авто-установки: {e}")

    # Запускаем установку вебхука один раз перед стартом сервера
    asyncio.run(on_startup())
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
