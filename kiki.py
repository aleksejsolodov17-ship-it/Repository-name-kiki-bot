import os, sqlite3, datetime, asyncio, io
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

# СУПЕР-СКОРОСТЬ: Глобальный клиент инициализируется один раз
giga = GigaChat(credentials=GIGA_KEY, verify_ssl_certs=False, scope="GIGACHAT_API_PERS")

# =========================
# 📊 БАЗА ДАННЫХ
# =========================
def init_db():
    with sqlite3.connect("kiki.db", check_same_thread=False) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, name TEXT, state TEXT DEFAULT 'idle', test_step INTEGER DEFAULT 0, test_score INTEGER DEFAULT 0, theme TEXT DEFAULT 'light')")
        conn.execute("CREATE TABLE IF NOT EXISTS memory (user_id INTEGER, role TEXT, content TEXT, timestamp DATETIME)")
        conn.execute("CREATE TABLE IF NOT EXISTS results (user_id INTEGER, score INTEGER, date TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS gratitude (user_id INTEGER, entry TEXT, date TEXT)")
init_db()

def db_query(sql, params=(), is_select=True):
    with sqlite3.connect("kiki.db", check_same_thread=False) as conn:
        cursor = conn.execute(sql, params)
        res = cursor.fetchall()
        conn.commit()
        return res if is_select else None

# =========================
# 🎮 КОНТЕНТ И КЛАВИАТУРЫ
# =========================
MAIN_KB = ReplyKeyboardMarkup([["🧠 Тест", "💬 AI"], ["📓 Дневник", "📊 Аналитика"], ["🎨 Тема", "🧘 Помощь"]], resize_keyboard=True)
TEST_QS = ["Как твоя энергия? (1-5)", "Уровень тревоги? (1-5)", "Качество сна? (1-5)", "Время на отдых? (1-5)"]
TIPS = {"🧘 Помощь": "Техника 5-4-3-2-1: Назови 5 предметов, которые видишь, 4, которые можешь потрогать, 3 звука, 2 запаха, 1 вкус. ✨"}

# =========================
# 🕹️ ГЛАВНАЯ ЛОГИКА
# =========================
async def handle_update(update: Update):
    if not update.message or not update.message.text: return
    text, user_id = update.message.text, update.message.from_user.id
    
    # Загружаем данные пользователя
    u = db_query("SELECT name, state, test_step, test_score FROM users WHERE user_id = ?", (user_id,))
    name, state, step, score = u[0] if u else ("друг", "idle", 0, 0)

    # 1. Команды /start и /name
    if text in ["/start", "/name"]:
        db_query("INSERT OR REPLACE INTO users (user_id, name, state) VALUES (?, ?, 'naming')", (user_id, name))
        await bot.send_message(user_id, "Привет! Я KiKi 🌿 Как мне к тебе обращаться?")
        return

    # 2. Регистрация имени
    if state == "naming":
        name = text.strip()[:15]
        db_query("UPDATE users SET name = ?, state = 'idle' WHERE user_id = ?", (name, user_id))
        await bot.send_message(user_id, f"Рада познакомиться, {name}! 😊", reply_markup=MAIN_KB)
        return

    # 3. Пошаговый Тест
    if text == "🧠 Тест" or state == "testing":
        if text == "🧠 Тест":
            db_query("UPDATE users SET state = 'testing', test_step = 0, test_score = 0 WHERE user_id = ?", (user_id,))
            await bot.send_message(user_id, TEST_QS[0], reply_markup=ReplyKeyboardMarkup([["1","2","3","4","5"]], resize_keyboard=True))
        else:
            val = int(text) if text.isdigit() else 3
            if step + 1 < len(TEST_QS):
                db_query("UPDATE users SET test_step = ?, test_score = ? WHERE user_id = ?", (step+1, score+val, user_id))
                await bot.send_message(user_id, TEST_QS[step+1])
            else:
                final = int(((score+val)/20)*100)
                db_query("UPDATE users SET state = 'idle' WHERE user_id = ?", (user_id,))
                db_query("INSERT INTO results VALUES (?, ?, ?)", (user_id, final, str(datetime.date.today())), False)
                await bot.send_message(user_id, f"Твой индекс благополучия: {final}% ✨", reply_markup=MAIN_KB)
        return

    # 4. Функциональные кнопки
    if text == "📊 Аналитика":
        await bot.send_message(user_id, "Строю твой график... 📈 (функция в разработке)", reply_markup=MAIN_KB)
        return

    if text == "🧘 Помощь":
        await bot.send_message(user_id, TIPS["🧘 Помощь"], reply_markup=MAIN_KB)
        return

    if text == "📓 Дневник":
        db_query("UPDATE users SET state = 'gratitude' WHERE user_id = ?", (user_id,))
        await bot.send_message(user_id, "Что хорошего случилось сегодня? ✨")
        return

    if state == "gratitude":
        db_query("INSERT INTO gratitude VALUES (?, ?, ?)", (user_id, text, str(datetime.date.today())), False)
        db_query("UPDATE users SET state = 'idle' WHERE user_id = ?", (user_id,))
        await bot.send_message(user_id, "Сохранила в твой дневник! 📔", reply_markup=MAIN_KB)
        return

    # 5. Реактивный AI Чат
    await bot.send_chat_action(user_id, "typing")
    try:
        hist_raw = db_query("SELECT role, content FROM memory WHERE user_id = ? ORDER BY timestamp DESC LIMIT 4", (user_id,))
        history = [{"role": r, "content": c} for r, c in reversed(hist_raw)]
        
        messages = [{"role": "system", "content": f"Ты KiKi, психолог. Собеседник: {name}. Отвечай мгновенно, тепло и вникай в каждое слово 🌿."}] + history + [{"role": "user", "content": text}]
        
        ans = giga.chat({"messages": messages}).choices[0].message.content
        
        db_query("INSERT INTO memory VALUES (?, 'user', ?, ?)", (user_id, text, datetime.datetime.now()), False)
        db_query("INSERT INTO memory VALUES (?, 'assistant', ?, ?)", (user_id, ans, datetime.datetime.now()), False)
        await bot.send_message(user_id, ans, reply_markup=MAIN_KB)
    except Exception as e:
        print(f"AI Error: {e}")
        await bot.send_message(user_id, "Я рядом. Что у тебя на душе? ✨", reply_markup=MAIN_KB)

# =========================
# 🌐 WEBHOOK
# =========================
@app.route("/webhook", methods=["POST"])
async def webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    await handle_update(update)
    return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
