import os, sqlite3, datetime, asyncio, io, threading, queue
import matplotlib.pyplot as plt
from flask import Flask, request
from telegram import Bot, Update, ReplyKeyboardMarkup
from gigachat import GigaChat

# --- КОНФИГУРАЦИЯ ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
GIGA_KEY = os.getenv("GIGACHAT_CREDENTIALS")
bot = Bot(token=TOKEN)
app = Flask(__name__)

# Очередь для обработки сообщений по порядку
user_queues = {}
queue_lock = threading.Lock()

# --- БАЗА ДАННЫХ ---
def db_query(sql, params=(), is_select=True):
    with sqlite3.connect("kiki.db", check_same_thread=False, timeout=30) as conn:
        cursor = conn.execute(sql, params)
        res = cursor.fetchall()
        conn.commit()
        return res if is_select else None

with sqlite3.connect("kiki.db") as conn:
    conn.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, name TEXT, state TEXT DEFAULT 'idle', test_step INTEGER DEFAULT 0, test_score INTEGER DEFAULT 0)")
    conn.execute("CREATE TABLE IF NOT EXISTS memory (user_id INTEGER, role TEXT, content TEXT, timestamp DATETIME)")
    conn.execute("CREATE TABLE IF NOT EXISTS results (user_id INTEGER, score INTEGER, date TEXT)")

# --- AI ЛОГИКА ---
async def ask_ai(user_id, text, name, mode="chat"):
    try:
        with GigaChat(credentials=GIGA_KEY, verify_ssl_certs=False, scope="GIGACHAT_API_PERS") as giga:
            if mode == "help":
                sys_prompt = f"Ты KiKi, эмпатичная девушка. {name} просит помощи. Поддержи тепло и предложи практики 🌿."
            else:
                sys_prompt = f"Ты KiKi, добрая девушка-психолог. Твой друг: {name}. Говори СТРОГО в женском роде, будь нежной 🌿."
            
            rows = db_query("SELECT role, content FROM memory WHERE user_id = ? ORDER BY timestamp DESC LIMIT 5", (user_id,))
            history = [{"role": r, "content": c} for r, c in reversed(rows)]
            messages = [{"role": "system", "content": sys_prompt}] + history + [{"role": "user", "content": text}]
            
            ans = giga.chat({"messages": messages}).choices[0].message.content
            
            db_query("INSERT INTO memory VALUES (?, ?, ?, ?)", (user_id, 'user', text, datetime.datetime.now()), False)
            db_query("INSERT INTO memory VALUES (?, ?, ?, ?)", (user_id, 'assistant', ans, datetime.datetime.now()), False)
            return ans
    except Exception as e:
        return f"Я рядом, {name}. ✨ Просто немного задумалась... (Ошибка связи)"

# --- ГРАФИКА ---
def create_chart(user_id):
    data = db_query("SELECT score, date FROM results WHERE user_id = ? ORDER BY date ASC LIMIT 10", (user_id,))
    if not data: return None
    scores, dates = [d[0] for d in data], [d[1][-5:] for d in data]
    plt.figure(figsize=(8, 4))
    plt.plot(dates, scores, marker='o', color='#7eb5a6', linewidth=3)
    plt.ylim(0, 105); plt.title("Твой прогресс 🌿")
    buf = io.BytesIO(); plt.savefig(buf, format='png'); buf.seek(0); plt.close()
    return buf

# --- ОБРАБОТЧИК ОЧЕРЕДИ ---
def worker(user_id, name):
    q = user_queues[user_id]
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    while not q.empty():
        text = q.get()
        loop.run_until_complete(bot.send_chat_action(user_id, "typing"))
        ans = loop.run_until_complete(ask_ai(user_id, text, name))
        loop.run_until_complete(bot.send_message(user_id, ans, reply_markup=MAIN_KB))
        q.task_done()
    with queue_lock: user_queues.pop(user_id, None)

# --- ГЛАВНАЯ ЛОГИКА ---
MAIN_KB = ReplyKeyboardMarkup([["🧠 Тест", "💬 AI"], ["📊 Аналитика", "🧘 Помощь"]], resize_keyboard=True)
TIPS_KB = ReplyKeyboardMarkup([["🆘 Тревога", "🌬️ Дыхание"], ["↩️ Назад"]], resize_keyboard=True)
TEST_QS = ["Как твоя энергия? (1-5)", "Уровень тревоги? (1-5)", "Качество сна? (1-5)", "Время на отдых? (1-5)"]

async def handle_update(update: Update):
    if not update.message or not update.message.text: return
    text, user_id = update.message.text, update.message.from_user.id
    
    u = db_query("SELECT name, state, test_step, test_score FROM users WHERE user_id = ?", (user_id,))
    name, state, step, score = u[0] if u else ("друг", "idle", 0, 0)

    if text in ["/start", "/name"]:
        db_query("INSERT OR REPLACE INTO users (user_id, name, state) VALUES (?, ?, 'naming')", (user_id, name), False)
        await bot.send_message(user_id, "Я проснулась! 🌿 Как мне к тебе обращаться?")
        return

    if state == "naming":
        name = text.strip()[:15]
        db_query("UPDATE users SET name = ?, state = 'idle' WHERE user_id = ?", (name, user_id), False)
        await bot.send_message(user_id, f"Рада знакомству, {name}! 😊", reply_markup=MAIN_KB)
        return

    # Функции: Тест, Аналитика, Помощь
    if text == "🧠 Тест" or state == "testing":
        if text == "🧠 Тест":
            db_query("UPDATE users SET state = 'testing', test_step = 0, test_score = 0 WHERE user_id = ?", (user_id,), False)
            await bot.send_message(user_id, TEST_QS[0], reply_markup=ReplyKeyboardMarkup([["1","2","3","4","5"]], resize_keyboard=True))
        else:
            val = int(text) if text.isdigit() else 3
            if step + 1 < len(TEST_QS):
                db_query("UPDATE users SET test_step = ?, test_score = ? WHERE user_id = ?", (step+1, score+val, user_id), False)
                await bot.send_message(user_id, TEST_QS[step+1])
            else:
                final = int(((score+val)/20)*100)
                db_query("UPDATE users SET state = 'idle' WHERE user_id = ?", (user_id,), False)
                db_query("INSERT INTO results VALUES (?, ?, ?)", (user_id, final, str(datetime.date.today())), False)
                await bot.send_message(user_id, f"Тест завершен! Твой индекс: {final}% ✨", reply_markup=MAIN_KB)
        return

    if text == "📊 Аналитика":
        chart = create_chart(user_id)
        if chart: await bot.send_photo(user_id, photo=chart, caption="Твой путь 📈")
        else: await bot.send_message(user_id, "Пройди тест! 🧠")
        return

    # AI Чат через Очередь
    with queue_lock:
        if user_id not in user_queues:
            user_queues[user_id] = queue.Queue()
            user_queues[user_id].put(text)
            threading.Thread(target=worker, args=(user_id, name)).start()
        else:
            user_queues[user_id].put(text)

@app.route("/webhook", methods=["POST"])
def webhook():
    threading.Thread(target=lambda: asyncio.run(handle_update(Update.de_json(request.get_json(force=True), bot)))).start()
    return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
