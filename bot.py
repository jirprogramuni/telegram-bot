import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import flask
import os
import logging
import pandas as pd
from datetime import datetime, timedelta
import requests
import io
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from apscheduler.schedulers.background import BackgroundScheduler

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Токен и админ
BOT_TOKEN = '7478861606:AAF-7eV0XjTn7S_6Q_caIk7Y27kGsfU_f-A'
ADMIN_ID = 476747112

bot = telebot.TeleBot(BOT_TOKEN)

# Состояния и pending
user_states = {}
pending_users = {}

# Google Sheets
EXCEL_URL = 'https://docs.google.com/spreadsheets/d/1SsG4uRtpslwSeZFZsIjWOAesrHvT6WhxrNoCgYRTUfg/export?format=xlsx'
TABEL_URL = 'https://docs.google.com/spreadsheets/d/1q6Rqx3ypWYZAD74MdH-iz-tN5aAANrnDglLysvHg9_8/export?format=xlsx'

SCOPE = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
CREDS_FILE = 'credentials.json'
creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
client = gspread.authorize(creds)
SHEET_ID = '1SsG4uRtpslwSeZFZsIjWOAesrHvT6WhxrNoCgYRTUfg'
sheet = client.open_by_key(SHEET_ID)

# --- ЭКРАНИРОВАНИЕ ---
def escape_markdown(text):
    if not text:
        return ""
    escape_chars = r'\_*[]()~`>#+-=|{}.!'
    return ''.join('\\' + c if c in escape_chars else c for c in str(text))

# --- Проверка регистрации ---
def is_registered(user_id):
    try:
        response = requests.get(EXCEL_URL)
        if response.status_code != 200:
            return False, None
        df = pd.read_excel(io.BytesIO(response.content), sheet_name="Список сотрудников", engine='openpyxl')
        row = df[df.iloc[:, 1] == user_id]
        if row.empty:
            return False, None
        return True, row.iloc[0, 0]
    except Exception as e:
        logging.error(f"Reg error: {e}")
        return False, None

# --- Зарплата ---
def get_salary_data(month_sheet, telegram_id):
    try:
        response = requests.get(EXCEL_URL)
        if response.status_code != 200:
            return [None] * 7
        df = pd.read_excel(io.BytesIO(response.content), sheet_name=month_sheet, engine='openpyxl')
        row = df[df.iloc[:, 1] == telegram_id]
        if row.empty:
            return [None] * 7
        name = row.iloc[0, 0]
        cols = df.columns
        h1 = row.iloc[0, cols.get_loc('Общие часы 1 половина')] if 'Общие часы 1 половина' in cols else 0
        h2 = row.iloc[0, cols.get_loc('Общие часы 2 половина')] if 'Общие часы 2 половина' in cols else 0
        a1 = row.iloc[0, cols.get_loc('Депозит 1')] if 'Депозит 1' in cols else 0
        a2 = row.iloc[0, cols.get_loc('Депозит 2')] if 'Депозит 2' in cols else 0
        total = row.iloc[0, cols.get_loc('Итоговая з/п')] if 'Итоговая з/п' in cols else 0
        return name, h1, h2, h1 + h2, a1, a2, total
    except Exception as e:
        logging.error(f"Salary error: {e}")
        return [None] * 7

# --- Табель ---
def get_tabel_data(user_name, month_sheet):
    try:
        response = requests.get(TABEL_URL)
        if response.status_code != 200:
            return []
        df = pd.read_excel(io.BytesIO(response.content), sheet_name=month_sheet, engine='openpyxl', header=None)
        header = df.iloc[0]
        points = {}
        current = None
        for col in range(2, len(df.columns)):
            if pd.notna(header[col]):
                current = header[col]
            if current:
                points[col] = current

        month_gen = {'Январь': 'января', 'Февраль': 'февраля', 'Март': 'марта', 'Апрель': 'апреля', 'Май': 'мая', 'Июнь': 'июня',
                     'Июль': 'июля', 'Август': 'августа', 'Сентябрь': 'сентября', 'Октябрь': 'октября', 'Ноябрь': 'ноября', 'Декабрь': 'декабря'}
        base = datetime(1899, 12, 30)
        shifts = []
        for r in range(1, len(df)):
            day = df.iloc[r, 0]
            serial = df.iloc[r, 1]
            if pd.isna(day) or pd.isna(serial):
                continue
            try:
                date = base + timedelta(days=float(serial)) if not isinstance(serial, datetime) else serial
            except:
                continue
            for col in range(2, len(df.columns)):
                cell = df.iloc[r, col]
                if isinstance(cell, str) and user_name in cell:
                    point = points.get(col, "Неизвестно")
                    shifts.append(f"{day}, {date.day} {month_gen.get(month_sheet, '')}: {point}")
        return shifts
    except Exception as e:
        logging.error(f"Tabel error: {e}")
        return []

# --- Напоминания ---
def send_reminders():
    try:
        df_emp = pd.read_excel(io.BytesIO(requests.get(EXCEL_URL).content), sheet_name="Список сотрудников", engine='openpyxl')
        name_to_id = {str(df_emp.iloc[i, 0]).strip(): int(df_emp.iloc[i, 1]) for i in range(len(df_emp)) if pd.notna(df_emp.iloc[i, 1])}

        tomorrow = datetime.now() + timedelta(days=1)
        months = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь']
        month_sheet = months[tomorrow.month - 1]
        gen = {'Январь': 'января', 'Февраль': 'февраля', 'Март': 'марта', 'Апрель': 'апреля', 'Май': 'мая', 'Июнь': 'июня',
               'Июль': 'июля', 'Август': 'августа', 'Сентябрь': 'сентября', 'Октябрь': 'октября', 'Ноябрь': 'ноября', 'Декабрь': 'декабря'}

        df_tabel = pd.read_excel(io.BytesIO(requests.get(TABEL_URL).content), sheet_name=month_sheet, engine='openpyxl', header=None)
        header = df_tabel.iloc[0]
        points = {}
        cur = None
        for c in range(2, len(df_tabel.columns)):
            if pd.notna(header[c]):
                cur = header[c]
            if cur:
                points[c] = cur

        serial = (tomorrow - datetime(1899, 12, 30)).days
        row = next((r for r in range(1, len(df_tabel)) if df_tabel.iloc[r, 1] == serial), None)
        if not row:
            return

        for c in range(2, len(df_tabel.columns)):
            cell = df_tabel.iloc[row, c]
            if isinstance(cell, str) and cell.strip():
                name = cell.strip()
                point = points.get(c, "Неизвестно")
                tid = name_to_id.get(name)
                if tid:
                    msg = f"*Напоминание:* завтра \\({tomorrow.day} {gen.get(month_sheet)}\\) смена в {escape_markdown(point)}\\. 📅"
                    bot.send_message(tid, msg, parse_mode='MarkdownV2')
    except Exception as e:
        logging.error(f"Reminder error: {e}")

# --- Меню ---
def get_main_menu_markup(reg):
    m = InlineKeyboardMarkup(row_width=2)
    if not reg:
        m.add(InlineKeyboardButton("Зарегистрироваться ✅", callback_data="register"))
    else:
        m.add(InlineKeyboardButton("Зарплата 💰", callback_data="salary"), InlineKeyboardButton("Табель 📅", callback_data="tabel"))
    m.add(InlineKeyboardButton("Форма 📝", url="https://docs.google.com/forms/u/0/d/e/1FAIpQLSdt4Xl89HwFdwWvGSzCxBh0zh-i2lQNcELEJYfspkyxmzGIsw/formResponse"))
    return m

def get_month_menu_markup():
    m = InlineKeyboardMarkup(row_width=3)
    m.add(InlineKeyboardButton("Октябрь", callback_data="month_Октябрь"),
          InlineKeyboardButton("Ноябрь", callback_data="month_Ноябрь"),
          InlineKeyboardButton("Декабрь", callback_data="month_Декабрь"))
    m.add(InlineKeyboardButton("Назад 🔙", callback_data="back_to_menu"))
    return m

# --- /start ---
@bot.message_handler(commands=['start'])
def start(message):
    uid = message.from_user.id
    reg, name = is_registered(uid)
    caption = f"*Добро пожаловать{', ' + escape_markdown(name) + '!' if reg else '!'}*\\n\\nВыберите действие\\."
    bot.send_photo(message.chat.id, open("photo_2025-10-28_01-49-34.jpg", "rb"), caption=caption, parse_mode='MarkdownV2', reply_markup=get_main_menu_markup(reg))

# --- Колбэки ---
@bot.callback_query_handler(func=lambda call: True)
def callback(call):
    uid = call.from_user.id
    reg, name = is_registered(uid)

    if call.data == "register":
        if reg:
            return bot.answer_callback_query(call.id, "Уже зарегистрированы!")
        user_states[uid] = "waiting_for_name"
        bot.send_message(uid, "*Введите имя:*", parse_mode='MarkdownV2')

    elif call.data == "salary":
        bot.edit_message_caption(chat_id=call.message.chat.id, message_id=call.message.message_id,
                                 caption="*Выберите месяц:*", parse_mode='MarkdownV2', reply_markup=get_month_menu_markup())

    elif call.data == "tabel":
        month = ['Январь','Февраль','Март','Апрель','Май','Июнь','Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь'][datetime.now().month-1]
        shifts = get_tabel_data(name, month)
        msg = f"*Смены за {month}:*\\n" + "\\n".join(f"\\- {escape_markdown(s)}" for s in shifts) if shifts else "*Нет смен\\.*"
        bot.send_message(call.message.chat.id, msg, parse_mode='MarkdownV2')
        bot.edit_message_caption(chat_id=call.message.chat.id, message_id=call.message.message_id,
                                 caption=f"*Привет, {escape_markdown(name)}\\!*", parse_mode='MarkdownV2', reply_markup=get_main_menu_markup(True))

    elif call.data.startswith("month_"):
        month = call.data.split("_")[1]
        data = get_salary_data(month, uid)
        if not data[0]:
            msg = "*Нет данных\\.*"
        else:
            n, h1, h2, th, a1, a2, ts = data
            msg = f"*{escape_markdown(n)}, {month}:*\\n\\n⏰ {h1} + {h2} = *{th}* ч\\n💰 {a1} + {a2} = *{ts}* руб\\."
        bot.send_message(call.message.chat.id, msg, parse_mode='MarkdownV2')
        bot.edit_message_caption(chat_id=call.message.chat.id, message_id=call.message.message_id,
                                 caption=f"*Привет, {escape_markdown(name)}\\!*", parse_mode='MarkdownV2', reply_markup=get_main_menu_markup(True))

    elif call.data == "back_to_menu":
        bot.edit_message_caption(chat_id=call.message.chat.id, message_id=call.message.message_id,
                                 caption=f"*Привет{', ' + escape_markdown(name) + '!' if reg else '!'}*\\n\\nМеню:", parse_mode='MarkdownV2', reply_markup=get_main_menu_markup(reg))

    # Админ
    elif call.data.startswith(("confirm_", "reject_")):
        if uid != ADMIN_ID:
            return bot.answer_callback_query(call.id, "Только админ!")
        target = int(call.data.split("_")[1])
        action = "подтверждена" if "confirm" in call.data else "отклонена"
        bot.answer_callback_query(call.id, "Готово!")
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        bot.send_message(target, f"*Регистрация {action}\\!*", parse_mode='MarkdownV2')
        if "confirm" in call.data and target in pending_users:
            r, n = is_registered(target)
            if r:
                bot.send_photo(target, open("photo_2025-10-28_01-49-34.jpg", "rb"),
                               caption="*Доступ открыт\\!*", parse_mode='MarkdownV2', reply_markup=get_main_menu_markup(True))
        if target in pending_users:
            del pending_users[target]

# --- Текст ---
@bot.message_handler(func=lambda m: True)
def text(message):
    uid = message.from_user.id
    if user_states.get(uid) == "waiting_for_name":
        name = message.text.strip()
        username = message.from_user.username or "Нет"
        pending_users[uid] = name
        bot.send_message(uid, "*Заявка отправлена\\!*", parse_mode='MarkdownV2')
        admin_msg = f"*Новая заявка!*\n*Имя:* {escape_markdown(name)}\n*Юзер:* @{escape_markdown(username)}\n*ID:* `{uid}`"
        markup = InlineKeyboardMarkup().add(
            InlineKeyboardButton("✅", callback_data=f"confirm_{uid}"),
            InlineKeyboardButton("❌", callback_data=f"reject_{uid}")
        )
        bot.send_message(ADMIN_ID, admin_msg, parse_mode='MarkdownV2', reply_markup=markup)
        del user_states[uid]

# --- Flask ---
app = flask.Flask(__name__)
@app.route('/', methods=['GET', 'HEAD'])
def index(): return ''
@app.route('/', methods=['POST'])
def webhook():
    if flask.request.headers.get('content-type') == 'application/json':
        bot.process_new_updates([telebot.types.Update.de_json(flask.request.get_data().decode('utf-8'))])
        return ''
    flask.abort(403)

if __name__ == '__main__':
    bot.remove_webhook()
    bot.set_webhook(url='https://telegram-bot-1-ydll.onrender.com')
    scheduler = BackgroundScheduler(timezone="Europe/Moscow")
    scheduler.add_job(send_reminders, 'cron', hour=20, minute=0)
    scheduler.start()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))