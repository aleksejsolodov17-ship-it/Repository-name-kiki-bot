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

# --- AI ЛОГИКА ---
def ask_ai(user_id, text, name, mode="chat"):
    try:
        with GigaChat(credentials=GIGA_KEY, verify_ssl_certs=False, scope="GIGACHAT_API_PERS") as giga:
            sys_prompt = f"Ты KiKi — нежная девушка-психолог. Твой друг: {name}. Говори СТРОГО в женском роде, очень кратко 🌿."
            if mode == "help": sys_prompt += " Сейчас поддержи его перед практиками."
            
            rows = db_query("SELECT role, content FROM memory WHERE user_id = ? ORDER BY timestamp DESC LIMIT 3", (user_id,))
            history = [{"role": r, "content": c} for r, c in reversed(rows)]
            messages = [{"role": "system", "content": sys_prompt}] + history + [{"role": "user", "content": text}]
            
            ans = giga.chat({"messages": messages}).choices[0].message.content
            db_query("INSERT INTO memory VALUES (?, 'user', ?, ?)", (user_id, text, datetime.datetime.now()), False)
            db_query("INSERT INTO memory VALUES (?, 'assistant', ?, ?)", (user_id, ans, datetime.datetime.now()), False)
            return ans
    except: return "Я рядом. ✨ Что на душе?"

# --- ГРАФИКА ---
def create_chart(user_id):
    u_res = db_query("SELECT theme FROM users WHERE user_id = ?", (user_id,))
    theme = u_res[0][0] if u_res else 'light'
    data = db_query("SELECT score, date FROM results WHERE user_id = ? ORDER BY date ASC LIMIT 10", (user_id,))
    if not data: return None
    scores = [d[0] for d in data]
    dates = [d[1][-5:] for d in data]
    plt.figure(figsize=(8, 4))
    plt.style.use('dark_background' if theme == 'dark' else 'default')
    plt.plot(dates, scores, marker='o', color='#7eb5a6', linewidth=3)
    plt.ylim(0, 105); plt.title("Твой путь 🌿")
    buf = io.BytesIO(); plt.savefig(buf, format='png', bbox_inches='tight'); buf.seek(0); plt.close()
    return buf

# --- ЛОГИКА БОТА ---
MAIN_KB = ReplyKeyboardMarkup([["🧠 Тест", "💬 AI"], ["📊 Аналитика", "🎨 Тема"], ["🧘 Помощь"]], resize_keyboard=True)
TEST_QS = ["Как энергия? (1-5)", "Уровень тревоги? (1-5)", "Сон? (1-5)", "Отдых? (1-5)"]

async def handle_msg(update: Update):
    if not update.message or not update.message.text: return
    text, user_id = update.message.text, update.message.from_user.id
    
    # Загружаем данные пользователя
    raw = db_query("SELECT name, state, test_step, test_score FROM users WHERE user_id = ?", (user_id,))
    name, state, step, score = raw[0] if raw else ("друг", "idle", 0, 0)

    # 1. ПРИОРИТЕТ: Команды и регистрация
    if "/start" in text or "/name" in text:
        db_query("INSERT OR REPLACE INTO users (user_id, name, state) VALUES (?, ?, 'naming')", (user_id, name), False)
        await bot.send_message(user_id, "Я проснулась! 🌿 Как мне к тебе обращаться?")
        return
    
    if state == "naming":
        db_query("UPDATE users SET name = ?, state = 'idle' WHERE user_id = ?", (text[:15], user_id), False)
        await bot.send_message(user_id, f"Рада знакомству, {text[:15]}!", reply_markup=MAIN_KB); return

    # 2. ПРИОРИТЕТ: Кнопки (строгое сравнение)
    if "Аналитика" in text:
        chart = create_chart(user_id)
        if chart: await bot.send_photo(user_id, photo=chart, caption="Твой ментальный путь 📈", reply_markup=MAIN_KB)
        else: await bot.send_message(user_id, "Данных пока нет. Пройди тест! 🧠", reply_markup=MAIN_KB)
        return

    if "Помощь" in text:
        ans = ask_ai(user_id, "Мне нужна помощь", name, mode="help")
        await bot.send_message(user_id, ans, reply_markup=MAIN_KB); return

    if "Тема" in text:
        u_t = db_query("SELECT theme FROM users WHERE user_id = ?", (user_id,))
        new_t = 'dark' if (not u_t or u_t[0][0] == 'light') else 'light'
        db_query("UPDATE users SET theme = ? WHERE user_id = ?", (new_t, user_id), False)
        await bot.send_message(user_id, f"Тема графиков изменена на {new_t}! 🎨"); return

    # 3. ТЕСТ
    if "Тест" in text or state == "testing":
        if "Тест" in text:
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
                db_query("INSERT INTO results (user_id, score, date) VALUES (?, ?, ?)", (user_id, final, str(datetime.date.today())), False)
                await bot.send_message(user_id, f"Тест окончен! ✨ Твой индекс: {final}%", reply_markup=MAIN_KB)
        return

    # 4. ПО УМОЛЧАНИЮ: AI Чат
    await bot.send_chat_action(user_id, "typing")
    ans = ask_ai(user_id, text, name)
    await bot.send_message(user_id, ans, reply_markup=MAIN_KB)

@app.route("/webhook", methods=["POST"])
def webhook():
    # Чтобы не было дублей, проверяем наличие данных
    if request.get_json():
        threading.Thread(target=lambda: asyncio.run(handle_msg(Update.de_json(request.get_json(force=True), bot)))).start()
    return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
