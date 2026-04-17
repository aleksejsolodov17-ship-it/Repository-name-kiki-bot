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
# 🧠 МОЗГ GIGACHAT
# =========================
def ask_ai(text):
    if not GIGA_KEY:
        return "KiKi 🌿: Привет! Настрой GIGACHAT_CREDENTIALS в панели Render."
    
    try:
        # scope="GIGACHAT_API_PERS" — критически важен для бесплатных ключей
        with GigaChat(credentials=GIGA_KEY, verify_ssl_certs=False, scope="GIGACHAT_API_PERS") as giga:
            response = giga.chat({
                "messages": [
                    {"role": "system", "content": "Ты KiKi — добрый ИИ-психолог. Отвечай тепло, коротко и по-русски."},
                    {"role": "user", "content": text}
                ]
            })
            return response.choices[0].message.content
    except Exception as e:
        print(f"❌ Ошибка GigaChat: {e}")
        return "KiKi 🌿: Я немного задумалась, но я всё равно рядом. Попробуй ещё раз?"

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

    if text == "/start":
        ai_mode.discard(user_id)
        user_state.pop(user_id, None)
        await bot.send_message(chat_id=user_id, text="Привет! Я KiKi 🌿 Твой AI-помощник. Чем займемся?", reply_markup=keyboard)
        return

    # Логика Теста
    if text == "🧠 Тест":
        ai_mode.discard(user_id)
        user_state[user_id] = {"step": 0, "score": 0}
        await bot.send_message(chat_id=user_id, text=questions[0], reply_markup=ReplyKeyboardMarkup([["Да", "Нет"]], resize_keyboard=True))
        return

    if user_id in user_state:
        st = user_state[user_id]
        if text.lower() in ["да", "yes", "ага"]: st["score"] += 1
        st["step"] += 1
        if st["step"] < len(questions):
            await bot.send_message(chat_id=user_id, text=questions[st["step"]])
        else:
            score = min(int((st["score"] / len(questions)) * 100), 100)
            save_result(user_id, score)
            await bot.send_message(chat_id=user_id, text=f"📊 Результат: {score}%\nKiKi рядом. Давай пообщаемся в ИИ-чате? 🌿", reply_markup=keyboard)
            user_state.pop(user_id, None)
        return

    # Режим AI
    if text == "💬 AI":
        ai_mode.add(user_id)
        await bot.send_message(chat_id=user_id, text="Режим AI включён. Расскажи, что тебя беспокоит? (Для выхода — /start)")
        return

    if user_id in ai_mode:
        await bot.send_chat_action(chat_id=user_id, action="typing")
        answer = ask_ai(text)
        await bot.send_message(chat_id=user_id, text=answer)
        return

# =========================
# 🌐 ROUTES
# =========================
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    update = Update.de_json(data, bot)
    # Используем create_task для неблокирующей работы
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(process_update(update))
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
            # Удаляем вебхук и ставим заново, очищая очередь сообщений
            await bot.delete_webhook(drop_pending_updates=True)
            await bot.set_webhook(url=f"{WEBHOOK_URL}/webhook")
            print("✅ Webhook установлен успешно!")
        except Exception as e:
            print(f"❌ Ошибка установки вебхука: {e}")

    # Запускаем один раз при старте
    try:
        asyncio.run(on_startup())
    except:
        pass

    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
