import os, sqlite3, datetime, asyncio, io, threading, queue, random
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
init_db()

# --- AI ЛОГИКА (С душой и женским родом) ---
async def ask_ai(user_id, text, name, mode="chat"):
    try:
        prefix = "Ты KiKi, эмпатичная девушка. Твой стиль: теплый, нежный, живой. "
        if mode == "initiative":
            sys_prompt = f"{prefix} Ты решила первой написать другу {name}, так как вы давно не общались. Придумай ОДНУ короткую, очень личную фразу или вопрос 🌿."
        else:
            sys_prompt = f"{prefix} Собеседник: {name}. Говори СТРОГО в женском роде (рада, пришла, видела). Отвечай на ВСЕ мысли в сообщении 🌿."
        
        rows = db_query("SELECT role, content FROM memory WHERE user_id = ? ORDER BY timestamp DESC LIMIT 6", (user_id,))
        history = [{"role": r, "content": c} for r, c in reversed(rows)]
        
        messages = [{"role": "system", "content": sys_prompt}] + history + [{"role": "user", "content": text}]
        ans = giga.chat({"messages": messages}).choices[0].message.content
        
        db_query("INSERT INTO memory VALUES (?, 'user', ?, ?)", (user_id, text, datetime.datetime.now()), False)
        db_query("INSERT INTO memory VALUES (?, 'assistant', ?, ?)", (user_id, ans, datetime.datetime.now()), False)
        return ans
    except:
        return "Я здесь, рядом. ✨ Просто на мгновение задумалась о нас..."

# --- ЛОГИКА ИНИЦИАТИВЫ (KiKi пишет сама) ---
def check_initiative():
    users = db_query("SELECT user_id, name FROM users WHERE state = 'idle'", is_select=True)
    for user_id, name in users:
        last_msg = db_query("SELECT timestamp FROM memory WHERE user_id = ? ORDER BY timestamp DESC LIMIT 1", (user_id,), is_select=True)
        if last_msg:
            # Парсим время (учитывая формат sqlite)
            l_time = datetime.datetime.strptime(last_msg[0][0].split('.')[0], '%Y-%m-%d %H:%M:%S')
            diff = (datetime.datetime.now() - l_time).total_seconds() / 3600
            
            # Если прошло больше 8 часов — KiKi проявляет нежность
            if diff > 8:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                msg = loop.run_until_complete(ask_ai(user_id, "Я скучаю, расскажи что-нибудь?", name, mode="initiative"))
                loop.run_until_complete(bot.send_message(user_id, msg, reply_markup=MAIN_KB))
                loop.close()

# --- КЛАВИАТУРЫ ---
MAIN_KB = ReplyKeyboardMarkup([["🧠 Тест", "💬 AI"], ["📊 Аналитика", "🧘 Помощь"]], resize_keyboard=True)
TEST_QS = ["Как энергия? (1-5)", "Уровень тревоги? (1-5)", "Качество сна? (1-5)", "Время на отдых? (1-5)"]

# --- ОБРАБОТЧИК (Worker) ---
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

async def handle_update(update: Update):
    if not update.message or not update.message.text: return
    text, user_id = update.message.text, update.message.from_user.id
    
    u_data = db_query("SELECT name, state, test_step, test_score FROM users WHERE user_id = ?", (user_id,))
    name, state, step, score = u_data[0] if u_data else ("друг", "idle", 0, 0)

    if text in ["/start", "/name"]:
        db_query("INSERT OR REPLACE INTO users (user_id, name, state) VALUES (?, ?, 'naming')", (user_id, name), False)
        await bot.send_message(user_id, "Привет! Я KiKi 🌿 Как мне к тебе обращаться?")
        return

    if state == "naming":
        new_name = text.strip()[:15]
        db_query("UPDATE users SET name = ?, state = 'idle' WHERE user_id = ?", (new_name, user_id), False)
        # Сразу сохраняем в память факт знакомства
        db_query("INSERT INTO memory VALUES (?, 'user', ?, ?)", (user_id, f"Меня зовут {new_name}", datetime.datetime.now()), False)
        db_query("INSERT INTO memory VALUES (?, 'assistant', ?, ?)", (user_id, f"Очень приятно, {new_name}!", datetime.datetime.now()), False)
        await bot.send_message(user_id, f"Рада знакомству, {new_name}! 😊 Расскажешь, как твои дела?", reply_markup=MAIN_KB)
        return

    # Логика Теста
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
                await bot.send_message(user_id, f"Мы закончили тест! ✨ Твой индекс благополучия: {final}%. Я рядом, если захочешь обсудить результаты.", reply_markup=MAIN_KB)
        return

    # AI Чат через очередь
    with queue_lock:
        if user_id not in user_queues:
            user_queues[user_id] = queue.Queue()
            user_queues[user_id].put(text)
            threading.Thread(target=worker, args=(user_id, name)).start()
        else:
            user_queues[user_id].put(text)

# --- WEBHOOK И ПЛАНИРОВЩИК ---
@app.route("/webhook", methods=["POST"])
def webhook():
    threading.Thread(target=lambda: asyncio.run(handle_update(Update.de_json(request.get_json(force=True), bot)))).start()
    return "ok", 200

if __name__ == "__main__":
    scheduler = BackgroundScheduler()
    # Проверяем каждые 4 часа, не пора ли KiKi проявить инициативу
    scheduler.add_job(check_initiative, 'interval', hours=4)
    scheduler.start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
