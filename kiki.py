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

# Глобальный клиент для скорости
giga = GigaChat(credentials=GIGA_KEY, verify_ssl_certs=False, scope="GIGACHAT_API_PERS")

user_queues = {}
queue_lock = threading.Lock()

# --- БАЗА ДАННЫХ ---
def db_query(sql, params=(), is_select=True):
    with sqlite3.connect("kiki.db", check_same_thread=False, timeout=60) as conn:
        cursor = conn.execute(sql, params)
        res = cursor.fetchall()
        conn.commit()
        return res if is_select else None

# --- AI ЛОГИКА ---
async def ask_ai(user_id, text, name):
    try:
        sys_prompt = f"Ты KiKi — теплый ИИ-психолог. Собеседник: {name}. Отвечай эмпатично, кратко и на русском 🌿."
        hist_raw = db_query("SELECT role, content FROM memory WHERE user_id = ? ORDER BY timestamp DESC LIMIT 5", (user_id,))
        history = [{"role": r, "content": c} for r, c in reversed(hist_raw)]
        
        messages = [{"role": "system", "content": sys_prompt}] + history + [{"role": "user", "content": text}]
        ans = giga.chat({"messages": messages}).choices[0].message.content
        
        db_query("INSERT INTO memory VALUES (?, 'user', ?, ?)", (user_id, text, datetime.datetime.now()), False)
        db_query("INSERT INTO memory VALUES (?, 'assistant', ?, ?)", (user_id, ans, datetime.datetime.now()), False)
        return ans
    except:
        return "Я рядом. ✨ Что на душе?"

# --- ГРАФИКА ---
def create_chart(user_id):
    data = db_query("SELECT date, score FROM results WHERE user_id = ? ORDER BY date ASC LIMIT 10", (user_id,))
    if not data: return None
    dates, scores = [d[0][-5:] for d in data], [d[1] for d in data]
    plt.figure(figsize=(8, 4))
    plt.plot(dates, scores, marker='o', color='#7eb5a6', linewidth=3)
    plt.fill_between(dates, scores, color='#7eb5a6', alpha=0.2)
    plt.ylim(0, 105); plt.title("Твой прогресс 🌿")
    buf = io.BytesIO(); plt.savefig(buf, format='png'); buf.seek(0); plt.close()
    return buf

# --- КОНТЕНТ ---
MAIN_KB = ReplyKeyboardMarkup([["🧠 Тест", "💬 AI"], ["📓 Дневник", "📊 Аналитика"], ["🎨 Тема", "🧘 Помощь"]], resize_keyboard=True)
TIPS_KB = ReplyKeyboardMarkup([["🆘 Тревога", "🌬️ Дыхание"], ["💡 Совет дня", "↩️ Назад"]], resize_keyboard=True)
TIPS = {
    "🆘 Тревога": "Техника 5-4-3-2-1: назови 5 предметов, которые видишь, 4, которые можешь потрогать, 3 звука, 2 запаха и 1 вкус. ✨",
    "🌬️ Дыхание": "Попробуй 'Квадратное дыхание': вдох на 4 счета, задержка на 4, выдох на 4, задержка на 4. Повтори 3 раза. 🌿",
    "💡 Совет дня": "Сегодня постарайся провести хотя бы 15 минут без телефона. Твоему мозгу нужна тишина. 📱❌"
}
TEST_QS = ["Как энергия? (1-5)", "Уровень тревоги? (1-5)", "Качество сна? (1-5)", "Время на отдых? (1-5)"]

# --- WORKER ---
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
async def handle_update(update: Update):
    if not update.message or not update.message.text: return
    text, user_id = update.message.text, update.message.from_user.id
    
    raw = db_query("SELECT name, state, test_step, test_score FROM users WHERE user_id = ?", (user_id,))
    # Безопасная распаковка
    if raw:
        name, state, step, score = raw[0]
    else:
        name, state, step, score = "друг", "idle", 0, 0

    # 1. Команды
    if text in ["/start", "/name"]:
        db_query("INSERT OR REPLACE INTO users (user_id, name, state) VALUES (?, ?, 'naming')", (user_id, name), False)
        await bot.send_message(user_id, "Привет! Я KiKi 🌿 Как мне к тебе обращаться?")
        return

    if state == "naming":
        clean_name = text.strip()[:15]
        db_query("UPDATE users SET name = ?, state = 'idle' WHERE user_id = ?", (clean_name, user_id), False)
        await bot.send_message(user_id, f"Рада знакомству, {clean_name}! 😊", reply_markup=MAIN_KB)
        return

    # 2. Функции (Тест, Помощь, Аналитика)
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
                db_query("INSERT INTO results VALUES (?, ?, ?)", (user_id, str(datetime.date.today()), final), False)
                await bot.send_message(user_id, f"Твой индекс благополучия: {final}% ✨", reply_markup=MAIN_KB)
        return

    if text == "📊 Аналитика":
        chart = create_chart(user_id)
        if chart: await bot.send_photo(user_id, photo=chart, caption="Твой ментальный путь 📈")
        else: await bot.send_message(user_id, "Данных пока нет. Пройди тест! 🧠")
        return

    if text == "🧘 Помощь" or text == "↩️ Назад":
        kb = TIPS_KB if text == "🧘 Помощь" else MAIN_KB
        msg = "Я подготовила практики самопомощи:" if text == "🧘 Помощь" else "Чем займемся?"
        await bot.send_message(user_id, msg, reply_markup=kb)
        return

    if text in TIPS:
        await bot.send_message(user_id, TIPS[text], reply_markup=TIPS_KB)
        return

    # 3. AI Чат (через очередь)
    with queue_lock:
        if user_id not in user_queues:
            user_queues[user_id] = queue.Queue()
            user_queues[user_id].put(text)
            threading.Thread(target=worker, args=(user_id, name)).start()
        else:
            user_queues[user_id].put(text)

# --- WEBHOOK ---
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    asyncio.run(handle_update(Update.de_json(data, bot)))
    return "ok", 200

if __name__ == "__main__":
    with sqlite3.connect("kiki.db") as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, name TEXT, state TEXT DEFAULT 'idle', test_step INTEGER DEFAULT 0, test_score INTEGER DEFAULT 0)")
        conn.execute("CREATE TABLE IF NOT EXISTS memory (user_id INTEGER, role TEXT, content TEXT, timestamp DATETIME)")
        conn.execute("CREATE TABLE IF NOT EXISTS results (user_id INTEGER, date TEXT, score INTEGER)")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
