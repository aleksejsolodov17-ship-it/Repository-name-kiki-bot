import os, sqlite3, datetime, asyncio, io, threading
import matplotlib.pyplot as plt
from flask import Flask, request
from telegram import Bot, Update, ReplyKeyboardMarkup
from gigachat import GigaChat
from apscheduler.schedulers.background import BackgroundScheduler

# --- КОНФИГУРАЦИЯ ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
GIGA_KEY = os.getenv("GIGACHAT_CREDENTIALS")
bot = Bot(token=TOKEN)
app = Flask(__name__)

# --- ИНИЦИАЛИЗАЦИЯ БД ---
def init_db():
    with sqlite3.connect("kiki.db", check_same_thread=False) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, name TEXT, state TEXT DEFAULT 'idle', test_step INTEGER DEFAULT 0, test_score INTEGER DEFAULT 0, theme TEXT DEFAULT 'light')")
        conn.execute("CREATE TABLE IF NOT EXISTS memory (user_id INTEGER, role TEXT, content TEXT, timestamp DATETIME)")
        conn.execute("CREATE TABLE IF NOT EXISTS results (user_id INTEGER, score INTEGER, date TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS gratitude (user_id INTEGER, entry TEXT, date TEXT)")
init_db()

def db_query(sql, params=(), is_select=False):
    with sqlite3.connect("kiki.db", check_same_thread=False) as conn:
        cursor = conn.execute(sql, params)
        return cursor.fetchall() if is_select else conn.commit()

# --- AI ЛОГИКА ---
def ask_ai(user_id, text, name):
    try:
        with GigaChat(credentials=GIGA_KEY, verify_ssl_certs=False, scope="GIGACHAT_API_PERS") as giga:
            sys_prompt = f"Ты KiKi — добрый ИИ-психолог. Пользователя зовут {name}. Отвечай тепло, коротко, по-русски 🌿."
            rows = db_query("SELECT role, content FROM memory WHERE user_id = ? ORDER BY timestamp DESC LIMIT 6", (user_id,), True)
            history = [{"role": r, "content": c} for r, c in reversed(rows)]
            
            messages = [{"role": "system", "content": sys_prompt}] + history + [{"role": "user", "content": text}]
            ans = giga.chat({"messages": messages}).choices[0].message.content
            
            db_query("INSERT INTO memory VALUES (?, 'user', ?, ?)", (user_id, text, datetime.datetime.now()))
            db_query("INSERT INTO memory VALUES (?, 'assistant', ?, ?)", (user_id, ans, datetime.datetime.now()))
            return ans
    except Exception as e:
        print(f"AI Error: {e}")
        return "Я здесь, просто настраиваюсь на твою волну... ✨"

# --- ГРАФИКА ---
def create_chart(user_id):
    u_res = db_query("SELECT theme FROM users WHERE user_id = ?", (user_id,), True)
    theme = u_res[0][0] if u_res else 'light'
    data = db_query("SELECT date, score FROM results WHERE user_id = ? ORDER BY date ASC LIMIT 10", (user_id,), True)
    
    if not data: return None
    dates, scores = [d[0][-5:] for d in data], [d[1] for d in data]
    
    plt.figure(figsize=(8, 4))
    plt.style.use('dark_background' if theme == 'dark' else 'default')
    color = '#a8e6cf' if theme == 'dark' else '#7eb5a6'
    plt.plot(dates, scores, marker='o', color=color, linewidth=3)
    plt.fill_between(dates, scores, color=color, alpha=0.2)
    plt.ylim(0, 105); plt.title("Твой путь 🌿", color=color)
    buf = io.BytesIO(); plt.savefig(buf, format='png'); buf.seek(0); plt.close()
    return buf

# --- КОНТЕНТ ---
MAIN_KB = ReplyKeyboardMarkup([["🧠 Тест", "💬 AI"], ["📓 Дневник", "📊 Аналитика"], ["🎨 Тема", "🧘 Помощь"]], resize_keyboard=True)
TIPS_KB = ReplyKeyboardMarkup([["🆘 Тревога", "🌬️ Дыхание"], ["💡 Совет дня", "↩️ Назад"]], resize_keyboard=True)
TIPS = {"🆘 Тревога": "Техника 5-4-3-2-1 заземляет. ✨", "🌬️ Дыхание": "Вдох на 4, задержка 4, выдох 8. 🌿"}
TEST_QUESTIONS = ["Как твоя энергия сегодня? (1-5)", "Уровень тревоги? (1-5)", "Как спалось? (1-5)", "Время на отдых было? (1-5)"]

# --- ГЛАВНАЯ ЛОГИКА ---
async def process_update(update: Update):
    if not update.message or not update.message.text: return
    text, user_id = update.message.text, update.message.from_user.id
    
    raw = db_query("SELECT name, state, test_step, test_score FROM users WHERE user_id = ?", (user_id,), True)
    name, state, step, score = raw[0] if raw else ("друг", "idle", 0, 0)

    if text == "/start" or text == "/name":
        db_query("INSERT OR REPLACE INTO users (user_id, name, state) VALUES (?, ?, 'naming')", (user_id, name))
        await bot.send_message(user_id, "Привет! Я KiKi 🌿 Как мне к тебе обращаться?")
        return

    if state == "naming":
        name = text.replace("Я", "").replace("зовут", "").strip(" ,.!")
        db_query("UPDATE users SET name = ?, state = 'idle' WHERE user_id = ?", (name, user_id))
        await bot.send_message(user_id, f"Приятно познакомиться, {name}! 😊", reply_markup=MAIN_KB)
        return

    if text == "🧠 Тест":
        db_query("UPDATE users SET state = 'testing', test_step = 0, test_score = 0 WHERE user_id = ?", (user_id,))
        await bot.send_message(user_id, TEST_QUESTIONS[0], reply_markup=ReplyKeyboardMarkup([["1","2","3","4","5"]], resize_keyboard=True))
        return

    if state == "testing":
        val = int(text) if text.isdigit() else 3
        new_score, new_step = score + val, step + 1
        if new_step < len(TEST_QUESTIONS):
            db_query("UPDATE users SET test_step = ?, test_score = ? WHERE user_id = ?", (new_step, new_score, user_id))
            await bot.send_message(user_id, TEST_QUESTIONS[new_step])
        else:
            final = int((new_score / (len(TEST_QUESTIONS)*5)) * 100)
            db_query("INSERT INTO results VALUES (?, ?, ?)", (user_id, final, str(datetime.date.today())))
            db_query("UPDATE users SET state = 'idle' WHERE user_id = ?", (user_id,))
            await bot.send_message(user_id, f"Твой индекс: {final}% ✨", reply_markup=MAIN_KB)
        return

    if text == "📊 Аналитика":
        chart = create_chart(user_id)
        if chart: await bot.send_photo(user_id, photo=chart, caption="Твой прогресс 📈")
        else: await bot.send_message(user_id, "Пройди тест!")
        return

    if text == "🎨 Тема":
        res = db_query("SELECT theme FROM users WHERE user_id = ?", (user_id,), True)
        new_t = 'dark' if (not res or res[0][0] == 'light') else 'light'
        db_query("UPDATE users SET theme = ? WHERE user_id = ?", (new_t, user_id))
        await bot.send_message(user_id, f"Тема: {new_t} 🎨")
        return

    if text == "🧘 Помощь":
        await bot.send_message(user_id, "SOS-практики:", reply_markup=TIPS_KB)
        return

    if text in TIPS:
        await bot.send_message(user_id, TIPS[text])
        return

    if text == "↩️ Назад":
        await bot.send_message(user_id, "Главное меню", reply_markup=MAIN_KB)
        return

    if text == "📓 Дневник":
        db_query("UPDATE users SET state = 'gratitude' WHERE user_id = ?", (user_id,))
        await bot.send_message(user_id, "Что хорошего случилось?")
        return

    if state == "gratitude":
        db_query("INSERT INTO gratitude VALUES (?, ?, ?)", (user_id, text, str(datetime.date.today())))
        db_query("UPDATE users SET state = 'idle' WHERE user_id = ?", (user_id,))
        await bot.send_message(user_id, "Сохранила! ✨", reply_markup=MAIN_KB)
        return

    # AI CHAT
    await bot.send_chat_action(user_id, "typing")
    ans = ask_ai(user_id, text, name)
    await bot.send_message(user_id, ans, reply_markup=MAIN_KB)

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    threading.Thread(target=lambda: asyncio.run(process_update(Update.de_json(data, bot)))).start()
    return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
