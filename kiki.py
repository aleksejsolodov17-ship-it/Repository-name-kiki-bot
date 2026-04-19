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

def init_db():
    with sqlite3.connect("kiki.db", check_same_thread=False) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, name TEXT, state TEXT DEFAULT 'idle', test_step INTEGER DEFAULT 0, test_score INTEGER DEFAULT 0)")
        conn.execute("CREATE TABLE IF NOT EXISTS memory (user_id INTEGER, role TEXT, content TEXT, timestamp DATETIME)")
        conn.execute("CREATE TABLE IF NOT EXISTS results (user_id INTEGER, score INTEGER, date TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS processed_updates (update_id INTEGER PRIMARY KEY)")
init_db()

# --- AI ЛОГИКА (Женский род + Поддержка) ---
async def ask_ai(user_id, text, name, mode="chat"):
    try:
        prefix = "Ты KiKi, эмпатичная девушка. "
        if mode == "help":
            sys_prompt = f"{prefix} Пользователь {name} нажал кнопку ПОМОЩЬ. Скажи что-то очень теплое, поддерживающее, чтобы он не чувствовал себя одиноко, и предложи выбрать практику ниже 🌿."
        else:
            sys_prompt = f"{prefix} Собеседник: {name}. Говори СТРОГО в женском роде. Будь ласковой и живой. 🌿"
        
        hist_raw = db_query("SELECT role, content FROM memory WHERE user_id = ? ORDER BY timestamp DESC LIMIT 5", (user_id,))
        history = [{"role": r, "content": c} for r, c in reversed(hist_raw)]
        
        messages = [{"role": "system", "content": sys_prompt}] + history + [{"role": "user", "content": text}]
        ans = giga.chat({"messages": messages}).choices[0].message.content
        
        db_query("INSERT INTO memory VALUES (?, 'user', ?, ?)", (user_id, text, datetime.datetime.now()), False)
        db_query("INSERT INTO memory VALUES (?, 'assistant', ?, ?)", (user_id, ans, datetime.datetime.now()), False)
        return ans
    except:
        return "Я рядом, {name}. Ты не один. ✨"

# --- КОНТЕНТ ---
MAIN_KB = ReplyKeyboardMarkup([["🧠 Тест", "💬 AI"], ["📊 Аналитика", "🧘 Помощь"]], resize_keyboard=True)
TIPS_KB = ReplyKeyboardMarkup([["🆘 Тревога", "🌬️ Дыхание"], ["💡 Совет дня", "↩️ Назад"]], resize_keyboard=True)
TIPS = {
    "🆘 Тревога": "Милая, давай заземлимся. Техника 5-4-3-2-1: назови 5 предметов вокруг... Я мысленно с тобой. ✨",
    "🌬️ Дыхание": "Давай подышим вместе? Вдох на 4 счета, задержка на 4, выдох на 4... У тебя отлично получается. 🌿",
    "💡 Совет дня": "Попробуй отложить телефон на 15 минут. Это время — только для тебя и твоей тишины. Я буду ждать тебя здесь. 📱❌"
}
TEST_QS = ["Как твоя энергия? (1-5)", "Уровень тревоги? (1-5)", "Качество сна? (1-5)", "Время на отдых? (1-5)"]

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
    text, user_id, up_id = update.message.text, update.message.from_user.id, update.update_id
    
    if db_query("SELECT update_id FROM processed_updates WHERE update_id = ?", (up_id,)): return
    db_query("INSERT INTO processed_updates VALUES (?)", (up_id,), False)

    res = db_query("SELECT name, state, test_step, test_score FROM users WHERE user_id = ?", (user_id,))
    name, state, step, score = res[0] if res else ("друг", "idle", 0, 0)

    if text in ["/start", "/name"]:
        db_query("INSERT OR REPLACE INTO users (user_id, name, state) VALUES (?, ?, 'naming')", (user_id, name), False)
        await bot.send_message(user_id, "Привет! Я KiKi 🌿 Как мне к тебе обращаться?")
        return

    if state == "naming":
        db_query("UPDATE users SET name = ?, state = 'idle' WHERE user_id = ?", (text[:15], user_id), False)
        await bot.send_message(user_id, f"Рада знакомству, {text[:15]}! 😊", reply_markup=MAIN_KB)
        return

    # ПОМОЩЬ (Грамотная и теплая)
    if text == "🧘 Помощь":
        await bot.send_chat_action(user_id, "typing")
        ai_support = await ask_ai(user_id, "Мне нужна помощь", name, mode="help")
        await bot.send_message(user_id, ai_support, reply_markup=TIPS_KB)
        return

    if text == "↩️ Назад":
        await bot.send_message(user_id, "Я здесь, возвращаемся в меню. 🌿", reply_markup=MAIN_KB)
        return

    if text in TIPS:
        await bot.send_message(user_id, TIPS[text], reply_markup=TIPS_KB)
        return

    # ТЕСТ (По одному вопросу)
    if text == "🧠 Тест" or state == "testing":
        if text == "🧠 Тест":
            db_query("UPDATE users SET state = 'testing', test_step = 0, test_score = 0 WHERE user_id = ?", (user_id,), False)
            await bot.send_message(user_id, TEST_QS[0], reply_markup=ReplyKeyboardMarkup([["1","2","3","4","5"]], resize_keyboard=True))
        else:
            val = int(text) if text.isdigit() else 3
            new_step = step + 1
            if new_step < len(TEST_QS):
                db_query("UPDATE users SET test_step = ?, test_score = ? WHERE user_id = ?", (new_step, score + val, user_id), False)
                await bot.send_message(user_id, TEST_QS[new_step])
            else:
                final = int(((score + val) / 20) * 100)
                db_query("UPDATE users SET state = 'idle' WHERE user_id = ?", (user_id,), False)
                db_query("INSERT INTO results VALUES (?, ?, ?)", (user_id, final, str(datetime.date.today())), False)
                await bot.send_message(user_id, f"Мы закончили! Твой индекс: {final}% ✨ Я очень рада, что ты заботишься о себе.", reply_markup=MAIN_KB)
        return

    # AI Чат (Очередь)
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
    threading.Thread(target=lambda: asyncio.run(handle_update(Update.de_json(data, bot)))).start()
    return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
