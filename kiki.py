import os, sqlite3, datetime, asyncio, io, threading
import matplotlib.pyplot as plt
from flask import Flask, request
from telegram import Bot, Update, ReplyKeyboardMarkup
from gigachat import GigaChat

# --- КОНФИГУРАЦИЯ ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
GIGA_KEY = os.getenv("GIGACHAT_CREDENTIALS")
bot = Bot(token=TOKEN)
app = Flask(__name__)

# --- БАЗА ДАННЫХ ---
def db_query(sql, params=(), is_select=True):
    with sqlite3.connect("kiki.db", check_same_thread=False, timeout=30) as conn:
        cursor = conn.execute(sql, params)
        res = cursor.fetchall()
        conn.commit()
        return res if is_select else None

with sqlite3.connect("kiki.db") as conn:
    conn.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, name TEXT, state TEXT DEFAULT 'idle', test_step INTEGER DEFAULT 0, test_score INTEGER DEFAULT 0)")
    conn.execute("CREATE TABLE IF NOT EXISTS results (user_id INTEGER, score INTEGER, date TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS memory (user_id INTEGER, role TEXT, content TEXT, timestamp DATETIME)")

# --- AI ЛОГИКА ---
def ask_ai(user_id, text, name, mode="chat"):
    try:
        with GigaChat(credentials=GIGA_KEY, verify_ssl_certs=False, scope="GIGACHAT_API_PERS") as giga:
            if mode == "help":
                sys_prompt = f"Ты KiKi, эмпатичная девушка. {name} просит ПОМОЩИ. Поддержи его очень тепло и скажи, что практики ниже помогут 🌿."
            else:
                sys_prompt = f"Ты KiKi — добрая девушка-психолог. Твой друг: {name}. Говори СТРОГО в женском роде, будь нежной и краткой 🌿."
            
            rows = db_query("SELECT role, content FROM memory WHERE user_id = ? ORDER BY timestamp DESC LIMIT 4", (user_id,))
            history = [{"role": r, "content": c} for r, c in reversed(rows)]
            messages = [{"role": "system", "content": sys_prompt}] + history + [{"role": "user", "content": text}]
            
            ans = giga.chat({"messages": messages}).choices[0].message.content
            db_query("INSERT INTO memory VALUES (?, 'user', ?, ?)", (user_id, text, datetime.datetime.now()), False)
            db_query("INSERT INTO memory VALUES (?, 'assistant', ?, ?)", (user_id, ans, datetime.datetime.now()), False)
            return ans
    except Exception as e:
        print(f"AI Error: {e}")
        return f"Я здесь, {name}. ✨ Просто немного задумалась... О чем ты хочешь поговорить?"

# --- ЛОГИКА БОТА ---
MAIN_KB = ReplyKeyboardMarkup([["🧠 Тест", "💬 AI"], ["📊 Аналитика", "🧘 Помощь"]], resize_keyboard=True)
TIPS_KB = ReplyKeyboardMarkup([["🆘 Тревога", "🌬️ Дыхание"], ["↩️ Назад"]], resize_keyboard=True)
TEST_QS = ["Как твоя энергия сегодня? (1-5)", "Уровень тревоги? (1-5)", "Качество сна? (1-5)", "Время на отдых? (1-5)"]

async def handle_msg(update: Update):
    if not update.message or not update.message.text: return
    text, user_id = update.message.text, update.message.from_user.id
    
    raw = db_query("SELECT name, state, test_step, test_score FROM users WHERE user_id = ?", (user_id,))
    name, state, step, score = raw[0] if raw else ("друг", "idle", 0, 0)

    # 1. Команды /start и /name
    if text in ["/start", "/name"]:
        db_query("INSERT OR REPLACE INTO users (user_id, name, state) VALUES (?, ?, 'naming')", (user_id, name), False)
        await bot.send_message(user_id, "Я проснулась! 🌿 Как мне к тебе обращаться?")
        return

    if state == "naming":
        new_name = text.strip()[:15]
        db_query("UPDATE users SET name = ?, state = 'idle' WHERE user_id = ?", (new_name, user_id), False)
        await bot.send_message(user_id, f"Рада познакомиться, {new_name}! 😊 Чем займемся?", reply_markup=MAIN_KB)
        return

    # 2. Логика ТЕСТА
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
                await bot.send_message(user_id, f"Тест окончен! ✨ Твой индекс благополучия: {final}%", reply_markup=MAIN_KB)
        return

    # 3. Кнопка ПОМОЩЬ (с ИИ-поддержкой)
    if text == "🧘 Помощь":
        ans = ask_ai(user_id, "Мне нужна помощь", name, mode="help")
        await bot.send_message(user_id, ans, reply_markup=TIPS_KB)
        return

    if text in ["🆘 Тревога", "🌬️ Дыхание"]:
        msg = "Давай заземлимся. Техника 5-4-3-2-1... ✨" if "Тревога" in text else "Давай подышим. Вдох на 4... 🌿"
        await bot.send_message(user_id, msg, reply_markup=TIPS_KB)
        return

    if text == "↩️ Назад":
        await bot.send_message(user_id, "Возвращаемся. 🌿", reply_markup=MAIN_KB)
        return

    # 4. ОБЫЧНЫЙ ЧАТ
    await bot.send_chat_action(user_id, "typing")
    ans = ask_ai(user_id, text, name)
    await bot.send_message(user_id, ans, reply_markup=MAIN_KB)

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    threading.Thread(target=lambda: asyncio.run(handle_msg(Update.de_json(data, bot)))).start()
    return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
