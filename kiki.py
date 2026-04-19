import os, sqlite3, datetime, asyncio, io, threading, queue
from flask import Flask, request
from telegram import Bot, Update, ReplyKeyboardMarkup
from gigachat import GigaChat

# --- КОНФИГУРАЦИЯ ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
GIGA_KEY = os.getenv("GIGACHAT_CREDENTIALS")
bot = Bot(token=TOKEN)
app = Flask(__name__)

# СУПЕР-СКОРОСТЬ: Глобальный клиент
giga = GigaChat(credentials=GIGA_KEY, verify_ssl_certs=False, scope="GIGACHAT_API_PERS")

# Очереди сообщений для защиты от "игнора"
user_queues = {}
queue_lock = threading.Lock()

# --- БАЗА ДАННЫХ ---
def init_db():
    with sqlite3.connect("kiki.db", check_same_thread=False) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, name TEXT, state TEXT DEFAULT 'idle', test_step INTEGER DEFAULT 0, test_score INTEGER DEFAULT 0)")
        conn.execute("CREATE TABLE IF NOT EXISTS memory (user_id INTEGER, role TEXT, content TEXT, timestamp DATETIME)")
        conn.execute("CREATE TABLE IF NOT EXISTS results (user_id INTEGER, score INTEGER, date TEXT)")
        conn.commit()

def db_query(sql, params=(), is_select=True):
    # Увеличен timeout до 60 сек, чтобы очередь не блокировала базу
    with sqlite3.connect("kiki.db", check_same_thread=False, timeout=60) as conn:
        cursor = conn.execute(sql, params)
        res = cursor.fetchall()
        conn.commit()
        return res if is_select else None

# --- AI ЛОГИКА ---
async def ask_ai(user_id, text, name):
    try:
        sys_prompt = f"Ты KiKi — теплый ИИ-психолог. Собеседник: {name}. Отвечай эмпатично, кратко и на все мысли юзера 🌿."
        # Подгружаем чуть больше истории для связности очереди
        hist_raw = db_query("SELECT role, content FROM memory WHERE user_id = ? ORDER BY timestamp DESC LIMIT 6", (user_id,))
        history = [{"role": r, "content": c} for r, c in reversed(hist_raw)]
        
        messages = [{"role": "system", "content": sys_prompt}] + history + [{"role": "user", "content": text}]
        ans = giga.chat({"messages": messages}).choices[0].message.content
        
        db_query("INSERT INTO memory VALUES (?, 'user', ?, ?)", (user_id, text, datetime.datetime.now()), False)
        db_query("INSERT INTO memory VALUES (?, 'assistant', ?, ?)", (user_id, ans, datetime.datetime.now()), False)
        return ans
    except Exception as e:
        print(f"AI Error: {e}")
        return "Я здесь, просто настраиваюсь на твою волну... ✨"

# --- ОБРАБОТЧИК ОЧЕРЕДИ (WORKER) ---
def worker(user_id, name):
    q = user_queues[user_id]
    # Создаем новый loop для асинхронных функций в потоке
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    while not q.empty():
        text = q.get()
        loop.run_until_complete(bot.send_chat_action(user_id, "typing"))
        ans = loop.run_until_complete(ask_ai(user_id, text, name))
        loop.run_until_complete(bot.send_message(user_id, ans, reply_markup=MAIN_KB))
        q.task_done()
    
    # Удаляем очередь после завершения всех задач
    with queue_lock:
        user_queues.pop(user_id, None)

# --- ГЛАВНАЯ ЛОГИКА ---
MAIN_KB = ReplyKeyboardMarkup([["🧠 Тест", "💬 AI"], ["📓 Дневник", "📊 Аналитика"], ["🎨 Тема", "🧘 Помощь"]], resize_keyboard=True)

async def handle_update(update: Update):
    if not update.message or not update.message.text: return
    text, user_id = update.message.text, update.message.from_user.id
    
    u_data = db_query("SELECT name, state FROM users WHERE user_id = ?", (user_id,))
    name, state = u_data[0] if u_data else ("друг", "idle")

    # Имя и команды — мгновенно
    if text in ["/start", "/name"]:
        db_query("INSERT OR REPLACE INTO users (user_id, name, state) VALUES (?, ?, 'naming')", (user_id, name), False)
        await bot.send_message(user_id, "Привет! Я KiKi 🌿 Как мне к тебе обращаться?")
        return

    if state == "naming":
        name = text.strip()[:15]
        db_query("UPDATE users SET name = ?, state = 'idle' WHERE user_id = ?", (name, user_id), False)
        await bot.send_message(user_id, f"Приятно познакомиться, {name}! 😊 Чем займемся?", reply_markup=MAIN_KB)
        return

    # Остальное — через очередь (чтобы не пропускать сообщения)
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
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
