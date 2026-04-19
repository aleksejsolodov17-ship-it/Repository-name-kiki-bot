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
# 📊 БАЗА ДАННЫХ
# =========================
def init_db():
    with sqlite3.connect("kiki.db", check_same_thread=False) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, name TEXT, theme TEXT DEFAULT 'light')")
        conn.execute("CREATE TABLE IF NOT EXISTS results (user_id INTEGER, score INTEGER, date TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS gratitude (user_id INTEGER, entry TEXT, date TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS memory (user_id INTEGER, role TEXT, content TEXT, timestamp DATETIME)")
init_db()

def save_memory(user_id, role, content):
    with sqlite3.connect("kiki.db") as conn:
        conn.execute("INSERT INTO memory VALUES (?, ?, ?, ?)", (user_id, role, content, datetime.datetime.now()))
        # Удаляем старые сообщения, оставляя только последние 8 для контекста
        conn.execute("DELETE FROM memory WHERE user_id = ? AND rowid NOT IN (SELECT rowid FROM memory WHERE user_id = ? ORDER BY timestamp DESC LIMIT 8)", (user_id, user_id))

# =========================
# 🧠 МОЗГ GIGACHAT
# =========================
def ask_ai(user_id, text):
    with sqlite3.connect("kiki.db") as conn:
        user_data = conn.execute("SELECT name FROM users WHERE user_id = ?", (user_id,)).fetchone()
    name = user_data[0] if user_data else "друг"
    
    try:
        with GigaChat(credentials=GIGA_KEY, verify_ssl_certs=False, scope="GIGACHAT_API_PERS") as giga:
            sys_msg = f"Ты KiKi — теплый ИИ-психолог. Пользователя зовут {name}. Отвечай кратко, эмпатично, используй эмодзи 🌿."
            
            with sqlite3.connect("kiki.db") as conn:
                rows = conn.execute("SELECT role, content FROM memory WHERE user_id = ? ORDER BY timestamp ASC", (user_id,)).fetchall()
                history = [{"role": r, "content": c} for r, c in rows]
            
            messages = [{"role": "system", "content": sys_msg}] + history + [{"role": "user", "content": text}]
            response = giga.chat({"messages": messages})
            ans = response.choices[0].message.content
            
            save_memory(user_id, "user", text)
            save_memory(user_id, "assistant", ans)
            return ans
    except Exception as e:
        print(f"Ошибка ИИ: {e}")
        return "Я здесь, просто настраиваюсь на твою волну... ✨ О чем хочешь поговорить?"

# =========================
# 📈 ГРАФИКА
# =========================
def create_trend_chart(user_id):
    with sqlite3.connect("kiki.db") as conn:
        res = conn.execute("SELECT theme FROM users WHERE user_id = ?", (user_id,)).fetchone()
        theme = res[0] if res else 'light'
        data = conn.execute("SELECT date, score FROM results WHERE user_id = ? ORDER BY date ASC LIMIT 10", (user_id,)).fetchall()
    
    if not data: return None
    dates, scores = [d[0][-5:] for d in data], [s[1] for s in data]
    
    plt.figure(figsize=(8, 4))
    plt.style.use('dark_background' if theme == 'dark' else 'default')
    color = '#a8e6cf' if theme == 'dark' else '#7eb5a6'
    
    plt.plot(dates, scores, marker='o', color=color, linewidth=3)
    plt.fill_between(dates, scores, color=color, alpha=0.2)
    plt.ylim(0, 105)
    plt.title("Твоя ментальная кривая 🌿", color=color)
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight')
    buf.seek(0)
    plt.close()
    return buf

# =========================
# 🎮 ЛОГИКА БОТА
# =========================
MAIN_KB = ReplyKeyboardMarkup([["🧠 Тест", "💬 AI"], ["📓 Дневник", "📊 Аналитика"], ["🎨 Тема", "🧘 Помощь"]], resize_keyboard=True)
TIPS = {"🆘 Тревога": "Техника 5-4-3-2-1 заземляет в моменте. ✨", "🌬️ Дыхание": "Вдох на 4, задержка на 4, выдох на 8. 🌿"}

user_state = {}

async def process_update(update: Update):
    if not update.message or not update.message.text: return
    text, user_id = update.message.text, update.message.from_user.id

    # 1. Приоритет: Команды
    if text == "/start":
        user_state.pop(user_id, None)
        with sqlite3.connect("kiki.db") as conn:
            user = conn.execute("SELECT name FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if not user:
            user_state[user_id] = {"step": "naming"}
            await bot.send_message(user_id, "Привет! Я KiKi 🌿 Как мне к тебе обращаться?")
        else:
            await bot.send_message(user_id, f"С возвращением, {user[0]}! Рада тебя видеть.", reply_markup=MAIN_KB)
        return

    if text == "/name":
        user_state[user_id] = {"step": "naming"}
        await bot.send_message(user_id, "Ой, я что-то напутала! Как твое настоящее имя? ✨")
        return

    # 2. Приоритет: Состояния (ввод данных)
    if user_id in user_state:
        state = user_state[user_id].get("step")
        
        if state == "naming":
            for word in ["Меня", "зовут", "Я", "я", "привет", "здравствуй"]:
                text = text.replace(word, "")
            clean_name = text.strip(" ,.!?")
            with sqlite3.connect("kiki.db") as conn:
                conn.execute("INSERT OR REPLACE INTO users (user_id, name) VALUES (?, ?)", (user_id, clean_name))
            user_state.pop(user_id)
            await bot.send_message(user_id, f"Приятно познакомиться, {clean_name}! 😊 Чем займемся?", reply_markup=MAIN_KB)
            return

        if state == "gratitude":
            with sqlite3.connect("kiki.db") as conn:
                conn.execute("INSERT INTO gratitude VALUES (?, ?, ?)", (user_id, text, str(datetime.date.today())))
            user_state.pop(user_id)
            answer = ask_ai(user_id, f"Я записал благодарность: {text}. Порадуйся за меня.")
            await bot.send_message(user_id, answer, reply_markup=MAIN_KB)
            return

    # 3. Кнопки меню
    if text == "📓 Дневник":
        user_state[user_id] = {"step": "gratitude"}
        await bot.send_message(user_id, "Что хорошего случилось сегодня? ✨")
        return

    if text == "📊 Аналитика":
        chart = create_trend_chart(user_id)
        if chart: await bot.send_photo(user_id, photo=chart, caption="Твой путь к гармонии. 🌿")
        else: await bot.send_message(user_id, "Данных пока нет. Пройди тест!")
        return

    if text == "🎨 Тема":
        with sqlite3.connect("kiki.db") as conn:
            res = conn.execute("SELECT theme FROM users WHERE user_id = ?", (user_id,)).fetchone()
            new_theme = 'dark' if (not res or res[0] == 'light') else 'light'
            conn.execute("UPDATE users SET theme = ? WHERE user_id = ?", (new_theme, user_id))
        await bot.send_message(user_id, f"Тема графиков теперь: **{new_theme}**! 🎨")
        return

    if text == "🧘 Помощь":
        kb = ReplyKeyboardMarkup([[k] for k in TIPS.keys()] + [["↩️ Назад"]], resize_keyboard=True)
        await bot.send_message(user_id, "Я здесь. Выбери практику:", reply_markup=kb)
        return

    # 4. По умолчанию — AI Чат
    if text != "↩️ Назад":
        await bot.send_chat_action(user_id, "typing")
        answer = ask_ai(user_id, text)
        await bot.send_message(user_id, answer)

# =========================
# ⏰ ПЛАНИРОВЩИК
# =========================
def daily_morning():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    with sqlite3.connect("kiki.db") as conn:
        users = conn.execute("SELECT user_id, name FROM users").fetchall()
    for uid, name in users:
        try: loop.run_until_complete(bot.send_message(uid, f"Доброе утро, {name}! ✨ Как самочувствие?"))
        except: pass

scheduler = BackgroundScheduler()
scheduler.add_job(daily_morning, 'cron', hour=9, minute=0)
scheduler.start()

# =========================
# 🌐 WEBHOOK
# =========================
@app.route("/webhook", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    threading.Thread(target=lambda: asyncio.run(process_update(update))).start()
    return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
