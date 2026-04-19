import os
import sqlite3
import datetime
import asyncio
import io
import threading
import matplotlib.pyplot as plt
from flask import Flask, request
from telegram import Bot, Update, ReplyKeyboardMarkup
from gigachat import GigaChat
from apscheduler.schedulers.background import BackgroundScheduler

# =========================
# 🔑 КОНФИГУРАЦИЯ
# =========================
TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
GIGA_KEY = os.getenv("GIGACHAT_CREDENTIALS")

bot = Bot(token=TOKEN)
app = Flask(__name__)

# =========================
# 📊 БАЗА ДАННЫХ И ПАМЯТЬ
# =========================
def init_db():
    with sqlite3.connect("kiki.db", check_same_thread=False) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS results (user_id INTEGER, score INTEGER, date TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS gratitude (user_id INTEGER, entry TEXT, date TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS wheel (user_id INTEGER, area TEXT, score INTEGER, date TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS memory (user_id INTEGER, role TEXT, content TEXT, timestamp DATETIME)")
init_db()

def save_memory(user_id, role, content):
    with sqlite3.connect("kiki.db") as conn:
        conn.execute("INSERT INTO memory VALUES (?, ?, ?, ?)", (user_id, role, content, datetime.datetime.now()))
        conn.execute("DELETE FROM memory WHERE rowid IN (SELECT rowid FROM memory WHERE user_id = ? ORDER BY timestamp DESC LIMIT -1 OFFSET 6)", (user_id,))

def get_chat_history(user_id):
    with sqlite3.connect("kiki.db") as conn:
        rows = conn.execute("SELECT role, content FROM memory WHERE user_id = ? ORDER BY timestamp ASC", (user_id,)).fetchall()
        return [{"role": r, "content": c} for r, c in rows]

# =========================
# 🧠 МОЗГ GIGACHAT
# =========================
def ask_ai(user_id, text, system_suffix=""):
    with sqlite3.connect("kiki.db") as conn:
        user_data = conn.execute("SELECT name FROM users WHERE user_id = ?", (user_id,)).fetchone()
    name = user_data[0] if user_data else "друг"
    
    history = get_chat_history(user_id)
    try:
        with GigaChat(credentials=GIGA_KEY, verify_ssl_certs=False, scope="GIGACHAT_API_PERS") as giga:
            sys_msg = f"Ты KiKi — теплый ИИ-психолог. Пользователя зовут {name}. Отвечай кратко, эмпатично. {system_suffix}"
            messages = [{"role": "system", "content": sys_msg}] + history + [{"role": "user", "content": text}]
            response = giga.chat({"messages": messages})
            ans = response.choices[0].message.content
            save_memory(user_id, "user", text)
            save_memory(user_id, "assistant", ans)
            return ans
    except:
        return f"{name}, я рядом, но мне нужно мгновение, чтобы собраться с мыслями. ✨"

# =========================
# 📈 ГРАФИКА (КОЛЕСО И ТРЕНД)
# =========================
def create_trend_chart(user_id):
    with sqlite3.connect("kiki.db") as conn:
        data = conn.execute("SELECT date, score FROM results WHERE user_id = ? ORDER BY date ASC LIMIT 10", (user_id,)).fetchall()
    if not data: return None
    dates = [d[0][-5:] for d in data]
    scores = [s[1] for s in data]
    plt.figure(figsize=(8, 4))
    plt.plot(dates, scores, marker='o', color='#7eb5a6', linewidth=3)
    plt.fill_between(dates, scores, color='#7eb5a6', alpha=0.2)
    plt.title("Твоя динамика благополучия 🌿")
    plt.ylim(0, 105)
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close()
    return buf

# =========================
# 🎮 ЛОГИКА БОТА И КОНТЕНТ
# =========================
MAIN_KB = ReplyKeyboardMarkup([["🧠 Тест", "💬 AI"], ["📓 Дневник", "📊 Аналитика"], ["🧘 Помощь"]], resize_keyboard=True)
WHEEL_AREAS = ["Здоровье", "Работа", "Окружение", "Отдых", "Душа"]
TIPS = {
    "🆘 Тревога": "Техника 5-4-3-2-1: Назови 5 предметов, которые видишь, 4, которые можешь потрогать, 3 звука, 2 запаха, 1 вкус. ✨",
    "🌬️ Дыхание": "Вдох на 4 счета, задержка на 4, выдох на 8. Повтори 3 раза. Это успокоит нервную систему.",
    "💡 Совет дня": "Попробуй сегодня 'правило 2 минут': если дело занимает меньше 2 минут, сделай его сразу, чтобы не грузить память."
}

user_state = {}

async def process_update(update: Update):
    if not update.message or not update.message.text: return
    text, user_id = update.message.text, update.message.from_user.id

    # 1. Регистрация имени
    with sqlite3.connect("kiki.db") as conn:
        user_data = conn.execute("SELECT name FROM users WHERE user_id = ?", (user_id,)).fetchone()

    if text == "/start":
        if not user_data:
            user_state[user_id] = {"step": "naming"}
            await bot.send_message(user_id, "Привет! Я KiKi 🌿 Твой островок спокойствия. Как мне к тебе обращаться?")
        else:
            await bot.send_message(user_id, f"С возвращением, {user_data[0]}! Рада тебя видеть.", reply_markup=MAIN_KB)
        return

    if user_id in user_state and user_state[user_id].get("step") == "naming":
        name = text.strip()[:20]
        with sqlite3.connect("kiki.db") as conn:
            conn.execute("INSERT OR REPLACE INTO users VALUES (?, ?)", (user_id, name))
        user_state.pop(user_id)
        await bot.send_message(user_id, f"Приятно познакомиться, {name}! Начнем наше путешествие?", reply_markup=MAIN_KB)
        return

    # 2. Дневник благодарности
    if text == "📓 Дневник":
        user_state[user_id] = {"step": "gratitude"}
        await bot.send_message(user_id, "Напиши 3 вещи, за которые ты благодарен сегодня. Это меняет фокус на позитив. ✨")
        return

    if user_id in user_state and user_state[user_id].get("step") == "gratitude":
        with sqlite3.connect("kiki.db") as conn:
            conn.execute("INSERT INTO gratitude VALUES (?, ?, ?)", (user_id, text, str(datetime.date.today())))
        feedback = ask_ai(user_id, f"Я записал благодарность: {text}. Поддержи меня.")
        await bot.send_message(user_id, feedback, reply_markup=MAIN_KB)
        user_state.pop(user_id)
        return

    # 3. Аналитика и графики
    if text == "📊 Аналитика":
        chart = create_trend_chart(user_id)
        if chart:
            await bot.send_photo(user_id, photo=chart, caption="Твой путь за последнее время. Ты молодец! 🌿")
        else:
            await bot.send_message(user_id, "Данных пока мало. Пройди тест!")
        return

    # 4. Помощь (SOS)
    if text == "🧘 Помощь":
        kb = ReplyKeyboardMarkup([[k] for k in TIPS.keys()] + [["↩️ Назад"]], resize_keyboard=True)
        await bot.send_message(user_id, "Я подготовила для тебя практики самопомощи:", reply_markup=kb)
        return
    
    if text in TIPS:
        await bot.send_message(user_id, TIPS[text])
        return

    # 5. AI Чат (по умолчанию)
    if text == "💬 AI" or text not in ["🧠 Тест", "📊 Аналитика", "📓 Дневник"]:
        if text == "↩️ Назад": 
            await bot.send_message(user_id, "Главное меню", reply_markup=MAIN_KB)
            return
        await bot.send_chat_action(user_id, "typing")
        await bot.send_message(user_id, ask_ai(user_id, text))

# =========================
# ⏰ ПЛАНИРОВЩИК (Уведомления)
# =========================
def daily_notifications():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    with sqlite3.connect("kiki.db") as conn:
        users = conn.execute("SELECT user_id, name FROM users").fetchall()
    for uid, name in users:
        try:
            loop.run_until_complete(bot.send_message(uid, f"Доброе утро, {name}! ✨ Не забудь сегодня уделить 5 минут себе. Как твое настроение?"))
        except: pass

scheduler = BackgroundScheduler()
scheduler.add_job(daily_notifications, 'cron', hour=9, minute=0)
scheduler.start()

# =========================
# 🌐 SERVER ROUTES
# =========================
@app.route("/webhook", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    threading.Thread(target=lambda: asyncio.run(process_update(update))).start()
    return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
