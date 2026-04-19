import os, sqlite3, datetime, asyncio, threading
from flask import Flask, request
from telegram import Bot, Update, ReplyKeyboardMarkup
from gigachat import GigaChat

# --- КОНФИГУРАЦИЯ ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
GIGA_KEY = os.getenv("GIGACHAT_CREDENTIALS")
bot = Bot(token=TOKEN)
app = Flask(__name__)

# --- БАЗА ДАННЫХ (Упрощенная) ---
def db_query(sql, params=(), is_select=True):
    with sqlite3.connect("kiki.db", check_same_thread=False, timeout=30) as conn:
        cursor = conn.execute(sql, params)
        res = cursor.fetchall()
        conn.commit()
        return res if is_select else None

# Инициализация БД
with sqlite3.connect("kiki.db") as conn:
    conn.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, name TEXT, state TEXT DEFAULT 'idle', test_step INTEGER DEFAULT 0, test_score INTEGER DEFAULT 0)")
    conn.execute("CREATE TABLE IF NOT EXISTS memory (user_id INTEGER, role TEXT, content TEXT, timestamp DATETIME)")
    conn.execute("CREATE TABLE IF NOT EXISTS results (user_id INTEGER, score INTEGER, date TEXT)")

# --- AI ЛОГИКА ---
def ask_ai(user_id, text, name):
    try:
        with GigaChat(credentials=GIGA_KEY, verify_ssl_certs=False, scope="GIGACHAT_API_PERS") as giga:
            sys_prompt = f"Ты KiKi — добрая девушка. Собеседник: {name}. Отвечай тепло, кратко и в женском роде 🌿."
            # Минимум истории для скорости
            rows = db_query("SELECT role, content FROM memory WHERE user_id = ? ORDER BY timestamp DESC LIMIT 2", (user_id,))
            history = [{"role": r, "content": c} for r, c in reversed(rows)]
            messages = [{"role": "system", "content": sys_prompt}] + history + [{"role": "user", "content": text}]
            
            ans = giga.chat({"messages": messages}).choices[0].message.content
            db_query("INSERT INTO memory VALUES (?, 'user', ?, ?)", (user_id, text, datetime.datetime.now()), False)
            db_query("INSERT INTO memory VALUES (?, 'assistant', ?, ?)", (user_id, ans, datetime.datetime.now()), False)
            return ans
    except Exception as e:
        print(f"AI ERROR: {e}")
        return "Я здесь, просто настраиваюсь на твою волну... ✨"

# --- ЛОГИКА БОТА ---
MAIN_KB = ReplyKeyboardMarkup([["🧠 Тест", "💬 AI"], ["📊 Аналитика", "🧘 Помощь"]], resize_keyboard=True)

async def handle_msg(update: Update):
    if not update.message or not update.message.text: return
    text, user_id = update.message.text, update.message.from_user.id
    
    # Получаем данные пользователя
    raw = db_query("SELECT name, state FROM users WHERE user_id = ?", (user_id,))
    name, state = raw[0] if raw else ("друг", "idle")

    if "/start" in text or "/name" in text:
        db_query("INSERT OR REPLACE INTO users (user_id, name, state) VALUES (?, ?, 'naming')", (user_id, name), False)
        await bot.send_message(user_id, "Я проснулась! 🌿 Как мне к тебе обращаться?")
        return

    if state == "naming":
        db_query("UPDATE users SET name = ?, state = 'idle' WHERE user_id = ?", (text[:15], user_id), False)
        await bot.send_message(user_id, f"Рада знакомству, {text[:15]}! 😊 Чем займемся?", reply_markup=MAIN_KB)
        return

    # Обычный AI чат
    await bot.send_chat_action(user_id, "typing")
    ans = ask_ai(user_id, text, name)
    await bot.send_message(user_id, ans, reply_markup=MAIN_KB)

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)
        update = Update.de_json(data, bot)
        threading.Thread(target=lambda: asyncio.run(handle_msg(update))).start()
    except Exception as e:
        print(f"Webhook Error: {e}")
    return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
