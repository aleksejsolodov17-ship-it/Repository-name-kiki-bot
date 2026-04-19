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

# Инициализация
with sqlite3.connect("kiki.db") as conn:
    conn.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, name TEXT, state TEXT DEFAULT 'idle', test_step INTEGER DEFAULT 0, test_score INTEGER DEFAULT 0)")
    conn.execute("CREATE TABLE IF NOT EXISTS memory (user_id INTEGER, role TEXT, content TEXT, timestamp DATETIME)")
    conn.execute("CREATE TABLE IF NOT EXISTS results (user_id INTEGER, score INTEGER, date TEXT)")

# --- AI ЛОГИКА ---
def ask_ai(user_id, text, name):
    try:
        with GigaChat(credentials=GIGA_KEY, verify_ssl_certs=False, scope="GIGACHAT_API_PERS") as giga:
            sys_prompt = f"Ты KiKi — нежная девушка-психолог. Твой друг: {name}. Говори СТРОГО в женском роде, будь эмпатичной и краткой 🌿."
            rows = db_query("SELECT role, content FROM memory WHERE user_id = ? ORDER BY timestamp DESC LIMIT 3", (user_id,))
            history = [{"role": r, "content": c} for r, c in reversed(rows)]
            messages = [{"role": "system", "content": sys_prompt}] + history + [{"role": "user", "content": text}]
            
            res = giga.chat({"messages": messages})
            ans = res.choices[0].message.content # Добавлен индекс [0]
            
            db_query("INSERT INTO memory VALUES (?, 'user', ?, ?)", (user_id, text, datetime.datetime.now()), False)
            db_query("INSERT INTO memory VALUES (?, 'assistant', ?, ?)", (user_id, ans, datetime.datetime.now()), False)
            return ans
    except Exception as e:
        print(f"AI ERROR: {e}")
        return "Я рядом. ✨ Просто на мгновение задумалась о чем-то важном..."

# --- ГРАФИКА ---
def create_chart(user_id):
    data = db_query("SELECT score, date FROM results WHERE user_id = ? ORDER BY date ASC LIMIT 10", (user_id,))
    if not data: return None
    scores = [d[0] for d in data]
    dates = [d[1][-5:] for d in data]
    plt.figure(figsize=(8, 4))
    plt.plot(dates, scores, marker='o', color='#7eb5a6', linewidth=3)
    plt.ylim(0, 105); plt.title("Твой ментальный путь 🌿")
    buf = io.BytesIO(); plt.savefig(buf, format='png'); buf.seek(0); plt.close()
    return buf

# --- ОБРАБОТЧИК ---
MAIN_KB = ReplyKeyboardMarkup([["🧠 Тест", "💬 AI"], ["📊 Аналитика", "🧘 Помощь"]], resize_keyboard=True)
TEST_QS = ["Как твоя энергия сегодня? (1-5)", "Уровень тревоги? (1-5)", "Качество сна? (1-5)", "Время на отдых? (1-5)"]

async def handle_msg(update: Update):
    if not update.message or not update.message.text: return
    text, user_id = update.message.text, update.message.from_user.id
    
    raw = db_query("SELECT name, state, test_step, test_score FROM users WHERE user_id = ?", (user_id,))
    name, state, step, score = raw[0] if raw else ("друг", "idle", 0, 0)

    # 1. Приоритет: Кнопки и команды (срабатывают мгновенно)
    if "/start" in text or "/name" in text:
        db_query("INSERT OR REPLACE INTO users (user_id, name, state) VALUES (?, ?, 'naming')", (user_id, name), False)
        await bot.send_message(user_id, "Я проснулась! 🌿 Как мне к тебе обращаться?")
        return

    if state == "naming":
        db_query("UPDATE users SET name = ?, state = 'idle' WHERE user_id = ?", (text[:15], user_id), False)
        await bot.send_message(user_id, f"Рада знакомству, {text[:15]}! 😊 Чем займемся?", reply_markup=MAIN_KB)
        return

    if "Тест" in text or state == "testing":
        if "Тест" in text:
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
                db_query("UPDATE users SET state = 'idle', test_step = 0 WHERE user_id = ?", (user_id,), False)
                db_query("INSERT INTO results VALUES (?, ?, ?)", (user_id, final, str(datetime.date.today())), False)
                await bot.send_message(user_id, f"Тест завершен! ✨ Твой индекс: {final}%", reply_markup=MAIN_KB)
        return

    if "Аналитика" in text:
        chart = create_chart(user_id)
        if chart: await bot.send_photo(user_id, photo=chart, caption="Твой прогресс 📈")
        else: await bot.send_message(user_id, "Данных пока нет. Пройди тест! 🧠")
        return

    if "Помощь" in text:
        await bot.send_message(user_id, "Давай заземлимся. Техника 5-4-3-2-1: назови 5 предметов вокруг... Я рядом. ✨", reply_markup=MAIN_KB)
        return

    # 2. По умолчанию: AI чат
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
