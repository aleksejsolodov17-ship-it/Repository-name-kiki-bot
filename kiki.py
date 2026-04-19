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
        conn.execute("DELETE FROM memory WHERE rowid IN (SELECT rowid FROM memory WHERE user_id = ? ORDER BY timestamp DESC LIMIT -1 OFFSET 6)", (user_id,))

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
            # Загружаем историю
            with sqlite3.connect("kiki.db") as conn:
                rows = conn.execute("SELECT role, content FROM memory WHERE user_id = ? ORDER BY timestamp ASC", (user_id,)).fetchall()
                history = [{"role": r, "content": c} for r, c in rows]
            
            messages = [{"role": "system", "content": sys_msg}] + history + [{"role": "user", "content": text}]
            response = giga.chat({"messages": messages})
            ans = response.choices[0].message.content
            save_memory(user_id, "user", text)
            save_memory(user_id, "assistant", ans)
            return ans
    except:
        return "Я рядом, просто задумалась о чем-то прекрасном... ✨ Что еще у тебя на душе?"

# =========================
# 📈 ГРАФИКА
# =========================
def create_trend_chart(user_id):
    with sqlite3.connect("kiki.db") as conn:
        res = conn.execute("SELECT theme FROM users WHERE user_id = ?", (user_id,)).fetchone()
        theme = res[0] if res else 'light'
        data = conn.execute("SELECT date, score FROM results WHERE user_id = ? ORDER BY date ASC LIMIT 10", (user_id,)).fetchall()
    
    if not data: return None
    
    dates = [d[0][-5:] for d in data]
    scores = [s[1] for s in data]
    
    # Стилизация
    plt.figure(figsize=(8, 4))
    if theme == 'dark':
        plt.style.use('dark_background')
        color = '#a8e6cf'
    else:
        plt.style.use('default')
        color = '#7eb5a6'
        
    plt.plot(dates, scores, marker='o', color=color, linewidth=3, markersize=8)
    plt.fill_between(dates, scores, color=color, alpha=0.2)
    plt.title("Твое состояние 🌿", color=color)
    plt.ylim(0, 105)
    plt.grid(True, alpha=0.2)
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight')
    buf.seek(0)
    plt.close()
    return buf

# =========================
# 🎮 ЛОГИКА БОТА
# =========================
MAIN_KB = ReplyKeyboardMarkup([["🧠 Тест", "💬 AI"], ["📓 Дневник", "📊 Аналитика"], ["🎨 Тема", "🧘 Помощь"]], resize_keyboard=True)
TIPS = {
    "🆘 Тревога": "Техника 5-4-3-2-1: Назови 5 предметов, которые видишь, 4, которые можешь потрогать, 3 звука, 2 запаха, 1 вкус. ✨",
    "🌬️ Дыхание": "Вдох на 4 счета, задержка на 4, выдох на 8. Это мгновенно успокаивает сердце. 🌿",
    "💡 Совет дня": "Попробуй практику 'Цифровой тишины': 15 минут без уведомлений и экранов."
}

user_state = {}

async def process_update(update: Update):
    if not update.message or not update.message.text: return
    text, user_id = update.message.text, update.message.from_user.id

    # --- Команды ---
    if text == "/start":
        with sqlite3.connect("kiki.db") as conn:
            user = conn.execute("SELECT name FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if not user:
            user_state[user_id] = {"step": "naming"}
            await bot.send_message(user_id, "Привет! Я KiKi 🌿 Твой островок спокойствия. Как мне к тебе обращаться?")
        else:
            await bot.send_message(user_id, f"С возвращением, {user[0]}! Рада тебя видеть.", reply_markup=MAIN_KB)
        return

    if text == "/name":
        user_state[user_id] = {"step": "naming"}
        await bot.send_message(user_id, "Ой, я что-то напутала! Как твое настоящее имя? ✨")
        return

    # --- Логика регистрации имени ---
    if user_id in user_state and user_state[user_id].get("step") == "naming":
        # Очистка имени от лишних слов
        for word in ["Меня", "зовут", "Я", "я", "привет", "Здравствуй"]:
            text = text.replace(word, "")
        clean_name = text.strip(" ,.!?")
        
        if len(clean_name) < 2:
            await bot.send_message(user_id, "Прости, не разобрала. Напиши просто своё имя:")
            return

        with sqlite3.connect("kiki.db") as conn:
            conn.execute("INSERT OR REPLACE INTO users (user_id, name) VALUES (?, ?)", (user_id, clean_name))
        
        user_state.pop(user_id)
        await bot.send_message(user_id, f"Приятно познакомиться, {clean_name}! Теперь я тебя запомнила. 😊", reply_markup=MAIN_KB)
        return

    # --- Функции ---
    if text == "📓 Дневник":
        user_state[user_id] = {"step": "gratitude"}
        await bot.send_message(user_id, "Напиши, что хорошего случилось сегодня? (Даже мелочи важны) ✨")
        return

    if user_id in user_state and user_state[user_id].get("step") == "gratitude":
        with sqlite3.connect("kiki.db") as conn:
            conn.execute("INSERT INTO gratitude VALUES (?, ?, ?)", (user_id, text, str(datetime.date.today())))
        feedback = ask_ai(user_id, f"Пользователь записал благодарность: {text}. Порадуйся за него.")
        await bot.send_message(user_id, feedback, reply_markup=MAIN_KB)
        user_state.pop(user_id)
        return

    if text == "📊 Аналитика":
        chart = create_trend_chart(user_id)
        if chart:
            await bot.send_photo(user_id, photo=chart, caption="Твой путь к гармонии. Ты большая умница! 🌿")
        else:
            await bot.send_message(user_id, "Пока данных нет. Пройди тест, чтобы я начала строить график!")
        return

    if text == "🎨 Тема":
        with sqlite3.connect("kiki.db") as conn:
            current = conn.execute("SELECT theme FROM users WHERE user_id = ?", (user_id,)).fetchone()
            new_theme = 'dark' if (not current or current[0] == 'light') else 'light'
            conn.execute("UPDATE users SET theme = ? WHERE user_id = ?", (new_theme, user_id))
        await bot.send_message(user_id, f"Тема графиков изменена на **{new_theme}**! 🎨")
        return

    if text == "🧘 Помощь":
        kb = ReplyKeyboardMarkup([[k] for k in TIPS.keys()] + [["↩️ Назад"]], resize_keyboard=True)
        await bot.send_message(user_id, "Я здесь. Выбери, что тебе нужно сейчас:", reply_markup=kb)
        return

    if text in TIPS:
        await bot.send_message(user_id, TIPS[text])
        return

    # --- AI Чат по умолчанию ---
    if text != "↩️ Назад":
        await bot.send_chat_action(user_id, "typing")
        await bot.send_message(user_id, ask_ai(user_id, text))

# =========================
# ⏰ ПЛАНИРОВЩИК
# =========================
def daily_morning():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    with sqlite3.connect("kiki.db") as conn:
        users = conn.execute("SELECT user_id, name FROM users").fetchall()
    for uid, name in users:
        try: loop.run_until_complete(bot.send_message(uid, f"Доброе утро, {name}! ✨ Как твое самочувствие сегодня? Не забудь улыбнуться себе в зеркале! 🌿"))
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
