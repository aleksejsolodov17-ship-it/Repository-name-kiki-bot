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

# Инициализация БД
with sqlite3.connect("kiki.db") as conn:
    conn.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, name TEXT, state TEXT DEFAULT 'idle', test_step INTEGER DEFAULT 0, test_score INTEGER DEFAULT 0)")
    conn.execute("CREATE TABLE IF NOT EXISTS memory (user_id INTEGER, role TEXT, content TEXT, timestamp DATETIME)")
    conn.execute("CREATE TABLE IF NOT EXISTS results (user_id INTEGER, score INTEGER, date TEXT)")

# --- УЛУЧШЕННАЯ AI ЛОГИКА ---
def ask_ai(user_id, text, name, mode="chat"):
    try:
        with GigaChat(credentials=GIGA_KEY, verify_ssl_certs=False, scope="GIGACHAT_API_PERS") as giga:
            # УСТАНОВКА: Имя + Пол + Внимательность
            sys_prompt = f"Ты KiKi — нежная девушка-психолог. Твой единственный и лучший друг — {name}. Говори СТРОГО в женском роде. Внимательно читай всё, что он пишет, и отвечай на все вопросы. Будь очень теплой 🌿."
            
            if mode == "help": 
                sys_prompt += f" Сейчас {name} просит помощи, поддержи его."

            # Загружаем историю (чуть больше для контекста)
            rows = db_query("SELECT role, content FROM memory WHERE user_id = ? ORDER BY timestamp DESC LIMIT 4", (user_id,))
            history = [{"role": r, "content": c} for r, c in reversed(rows)]
            
            messages = [{"role": "system", "content": sys_prompt}] + history + [{"role": "user", "content": text}]
            
            res = giga.chat({"messages": messages})
            ans = res.choices[0].message.content
            
            # Сохраняем в память
            db_query("INSERT INTO memory VALUES (?, 'user', ?, ?)", (user_id, text, datetime.datetime.now()), False)
            db_query("INSERT INTO memory VALUES (?, 'assistant', ?, ?)", (user_id, ans, datetime.datetime.now()), False)
            return ans
    except Exception as e:
        print(f"AI ERROR: {e}")
        return f"Я здесь, {name}. 🌿 Просто на мгновение задумалась о чем-то своем. Что ты хотел рассказать?"

# --- ЛОГИКА БОТА ---
MAIN_KB = ReplyKeyboardMarkup([["🧠 Тест", "💬 AI"], ["📊 Аналитика", "🧘 Помощь"]], resize_keyboard=True)

async def handle_msg(update: Update):
    if not update.message or not update.message.text: return
    text, user_id = update.message.text, update.message.from_user.id
    
    raw = db_query("SELECT name, state FROM users WHERE user_id = ?", (user_id,))
    name, state = raw[0] if raw else ("друг", "idle")

    # Регистрация и команды
    if "/start" in text or "/name" in text:
        db_query("INSERT OR REPLACE INTO users (user_id, name, state) VALUES (?, ?, 'naming')", (user_id, name), False)
        await bot.send_message(user_id, "Я проснулась! 🌿 Как мне к тебе обращаться?")
        return

    if state == "naming":
        new_name = text.strip()[:15]
        db_query("UPDATE users SET name = ?, state = 'idle' WHERE user_id = ?", (new_name, user_id), False)
        # Записываем знакомство в память ИИ
        db_query("INSERT INTO memory VALUES (?, 'assistant', ?, ?)", (user_id, f"Рада знакомству, {new_name}!", datetime.datetime.now()), False)
        await bot.send_message(user_id, f"Рада познакомиться, {new_name}! 😊 Чем займемся?", reply_markup=MAIN_KB)
        return

    # Перехват кнопок
    if "Помощь" in text:
        ans = ask_ai(user_id, "Мне нужна помощь", name, mode="help")
        await bot.send_message(user_id, ans, reply_markup=MAIN_KB); return

    if "Аналитика" in text:
        await bot.send_message(user_id, f"{name}, я еще коплю данные, чтобы построить твой график. Давай пройдем тест? 📈", reply_markup=MAIN_KB); return

    # Обычный чат
    await bot.send_chat_action(user_id, "typing")
    ans = ask_ai(user_id, text, name)
    await bot.send_message(user_id, ans, reply_markup=MAIN_KB)

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    if data:
        threading.Thread(target=lambda: asyncio.run(handle_msg(Update.de_json(data, bot)))).start()
    return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
