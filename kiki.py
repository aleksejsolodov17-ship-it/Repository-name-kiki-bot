import os, sqlite3, datetime, asyncio, io, threading
import matplotlib.pyplot as plt
from flask import Flask, request
from telegram import Bot, Update, ReplyKeyboardMarkup
from gigachat import GigaChat

# =========================
# 🔑 КОНФИГУРАЦИЯ
# =========================
TOKEN = os.getenv("TELEGRAM_TOKEN")
GIGA_KEY = os.getenv("GIGACHAT_CREDENTIALS")
bot = Bot(token=TOKEN)
app = Flask(__name__)

# =========================
# 📊 БАЗА ДАННЫХ
# =========================
def init_db():
    with sqlite3.connect("kiki.db", check_same_thread=False) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, name TEXT, state TEXT DEFAULT 'idle', test_step INTEGER DEFAULT 0, test_score INTEGER DEFAULT 0)")
        conn.execute("CREATE TABLE IF NOT EXISTS memory (user_id INTEGER, role TEXT, content TEXT, timestamp DATETIME)")
        conn.execute("CREATE TABLE IF NOT EXISTS results (user_id INTEGER, score INTEGER, date TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS gratitude (user_id INTEGER, entry TEXT, date TEXT)")
init_db()

def db_query(sql, params=(), is_select=False):
    with sqlite3.connect("kiki.db", check_same_thread=False) as conn:
        cursor = conn.execute(sql, params)
        return cursor.fetchall() if is_select else conn.commit()

# =========================
# 🧠 МОЗГ GIGACHAT
# =========================
def ask_ai(user_id, text, name):
    try:
        with GigaChat(credentials=GIGA_KEY, verify_ssl_certs=False, scope="GIGACHAT_API_PERS") as giga:
            sys_prompt = f"Ты KiKi — добрый ИИ-психолог. Пользователя зовут {name}. Отвечай тепло, коротко, используй 🌿."
            rows = db_query("SELECT role, content FROM memory WHERE user_id = ? ORDER BY timestamp DESC LIMIT 6", (user_id,), True)
            history = [{"role": r, "content": c} for r, c in reversed(rows)]
            
            messages = [{"role": "system", "content": sys_prompt}] + history + [{"role": "user", "content": text}]
            ans = giga.chat({"messages": messages}).choices[0].message.content
            
            db_query("INSERT INTO memory VALUES (?, 'user', ?, ?)", (user_id, text, datetime.datetime.now()))
            db_query("INSERT INTO memory VALUES (?, 'assistant', ?, ?)", (user_id, ans, datetime.datetime.now()))
            return ans
    except Exception as e:
        print(f"AI Error: {e}")
        return "Я рядом, просто глубоко задумалась... ✨ Расскажешь что-нибудь еще?"

# =========================
# 📈 ГРАФИКА
# =========================
def create_chart(user_id):
    data = db_query("SELECT date, score FROM results WHERE user_id = ? ORDER BY date ASC LIMIT 10", (user_id,), True)
    if not data: return None
    dates, scores = [d[0][-5:] for d in data], [d[1] for d in data]
    plt.figure(figsize=(8, 4))
    plt.plot(dates, scores, marker='o', color='#7eb5a6', linewidth=3)
    plt.fill_between(dates, scores, color='#7eb5a6', alpha=0.2)
    plt.ylim(0, 105); plt.title("Твой прогресс 🌿")
    buf = io.BytesIO(); plt.savefig(buf, format='png'); buf.seek(0); plt.close()
    return buf

# =========================
# 🎮 ЛОГИКА БОТА
# =========================
MAIN_KB = ReplyKeyboardMarkup([["🧠 Тест", "💬 AI"], ["📓 Дневник", "📊 Аналитика"]], resize_keyboard=True)
TEST_QUESTIONS = [
    "Как ты оценишь свой уровень энергии сегодня? (1-5)",
    "Часто ли ты чувствуешь тревогу на этой неделе? (1-5)",
    "Удается ли тебе находить время на отдых? (1-5)",
    "Как ты оценишь качество своего сна? (1-5)"
]

async def process_update(update: Update):
    if not update.message or not update.message.text: return
    text, user_id = update.message.text, update.message.from_user.id
    
    user_data = db_query("SELECT name, state, test_step, test_score FROM users WHERE user_id = ?", (user_id,), True)
    name, state, step, score = user_data[0] if user_data else ("друг", "idle", 0, 0)

    # --- Команды ---
    if text == "/start" or text == "/name":
        db_query("INSERT OR REPLACE INTO users (user_id, name, state) VALUES (?, ?, 'naming')", (user_id, name))
        await bot.send_message(user_id, "Привет! Я KiKi 🌿 Как мне к тебе обращаться?")
        return

    # --- Состояние: Имя ---
    if state == "naming":
        clean_name = text.replace("Я", "").replace("Меня зовут", "").strip(" ,.!")
        db_query("UPDATE users SET name = ?, state = 'idle' WHERE user_id = ?", (clean_name, user_id))
        await bot.send_message(user_id, f"Приятно познакомиться, {clean_name}! 😊", reply_markup=MAIN_KB)
        return

    # --- Состояние: Тест ---
    if text == "🧠 Тест" or state == "testing":
        if text == "🧠 Тест": 
            step, score = 0, 0
            db_query("UPDATE users SET state = 'testing', test_step = 0, test_score = 0 WHERE user_id = ?", (user_id,))
        else:
            val = int(text) if text.isdigit() else 3
            score += val
            step += 1
        
        if step < len(TEST_QUESTIONS):
            db_query("UPDATE users SET test_step = ?, test_score = ? WHERE user_id = ?", (step, score, user_id))
            await bot.send_message(user_id, TEST_QUESTIONS[step], reply_markup=ReplyKeyboardMarkup([["1","2","3","4","5"]], resize_keyboard=True))
        else:
            final_score = int((score / (len(TEST_QUESTIONS)*5)) * 100)
            db_query("INSERT INTO results VALUES (?, ?, ?)", (user_id, final_score, str(datetime.date.today())))
            db_query("UPDATE users SET state = 'idle', test_step = 0 WHERE user_id = ?", (user_id,))
            await bot.send_message(user_id, f"Тест окончен! Твой уровень благополучия: {final_score}% ✨", reply_markup=MAIN_KB)
        return

    # --- Функции ---
    if text == "📊 Аналитика":
        chart = create_chart(user_id)
        if chart: await bot.send_photo(user_id, photo=chart, caption="Твой ментальный путь 📈")
        else: await bot.send_message(user_id, "Данных для графика пока нет. Пройди тест!")
        return

    if text == "📓 Дневник":
        db_query("UPDATE users SET state = 'gratitude' WHERE user_id = ?", (user_id,))
        await bot.send_message(user_id, "Напиши, что хорошего случилось сегодня? ✨")
        return

    if state == "gratitude":
        db_query("INSERT INTO gratitude VALUES (?, ?, ?)", (user_id, text, str(datetime.date.today())))
        db_query("UPDATE users SET state = 'idle' WHERE user_id = ?", (user_id,))
        await bot.send_message(user_id, "Записала в твой дневник. Это важный шаг! 📔", reply_markup=MAIN_KB)
        return

    # --- AI Чат ---
    await bot.send_chat_action(user_id, "typing")
    ans = ask_ai(user_id, text, name)
    await bot.send_message(user_id, ans)

# =========================
# 🌐 WEBHOOK
# =========================
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    threading.Thread(target=lambda: asyncio.run(process_update(Update.de_json(data, bot)))).start()
    return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
