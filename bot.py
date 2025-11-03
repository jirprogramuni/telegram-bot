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

# Логи
logging.basicConfig(level=logging.INFO)

# Токен и админ
BOT_TOKEN = '7478861606:AAF-7eV0XjTn7S_6Q_caIk7Y27kGsfU_f-A'
ADMIN_ID = 476747112

bot = telebot.TeleBot(BOT_TOKEN)

# Состояния
user_states = {}
pending_users = {}

# Sheets URL
EXCEL_URL = 'https://docs.google.com/spreadsheets/d/1SsG4uRtpslwSeZFZsIjWOAesrHvT6WhxrNoCgYRTUfg/export?format=xlsx'
TABEL_URL = 'https://docs.google.com/spreadsheets/d/1q6Rqx3ypWYZAD74MdH-iz-tN5aAANrnDglLysvHg9_8/export?format=xlsx'

# Google API
SCOPE = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
CREDS_FILE = 'credentials.json'
creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
client = gspread.authorize(creds)
SHEET_ID = '1SsG4uRtpslwSeZFZsIjWOAesrHvT6WhxrNoCgYRTUfg'
sheet = client.open_by_key(SHEET_ID)

# Экранирование MarkdownV2
def escape_markdown(text):
    if not text:
        return ""
    escape_chars = r'\_*[]()~`>#+-=|{}.!'
    return ''.join('\\' + c if c in escape_chars else c for c in str(text))

# Проверка регистрации
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
        logging.error(f"Ошибка регистрации: {e}")
        return False, None

# Зарплата
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
        columns = df.columns
        hours_first = row.iloc[0, columns.get_loc('Общие часы 1 половина')] if 'Общие часы 1 половина' in columns else 0
        hours_second = row.iloc[0, columns.get_loc('Общие часы 2 половина')] if 'Общие часы 2 половина' in columns else 0
        first_advance = row.iloc[0, columns.get_loc('Депозит 1')] if 'Депозит 1' in columns else 0
        second_advance = row.iloc[0, columns.get_loc('Депозит 2')] if 'Депозит 2' in columns else 0
        total_salary = row.iloc[0, columns.get_loc('Итоговая з/п')] if 'Итоговая з/п' in columns else 0
        return name, hours_first, hours_second, hours_first + hours_second, first_advance, second_advance, total_salary
    except Exception as e:
        logging.error(f"Ошибка зарплаты: {e}")
        return [None] * 7

# Табель
def get_tabel_data(user_name, month_sheet):
    try:
        response = requests.get(TABEL_URL)
        if response.status_code != 200:
            return []
        df = pd.read_excel(io.BytesIO(response.content), sheet_name=month_sheet, engine='openpyxl', header=None, parse_dates=False)
        header = df.iloc[0]
        points = {}
        current_point = None
        for col in range(2, df.shape[1]):
            if pd.notna(header[col]):
                current_point = header[col]
            if current_point:
                points[col] = current_point

        month_genitive = {
            'Январь': 'января', 'Февраль': 'февраля', 'Март': 'марта', 'Апрель': 'апреля',
            'Май': 'мая', 'Июнь': 'июня', 'Июль': 'июля', 'Август': 'августа',
            'Сентябрь': 'сентября', 'Октябрь': 'октября', 'Ноябрь': 'ноября', 'Декабрь': 'декабря'
        }
        base = datetime(1899, 12, 30)
        shifts = []
        for row_idx in range(1, df.shape[0]):
            day_abbr = df.iloc[row_idx, 0]
            serial = df.iloc[row_idx, 1]
            if pd.isna(day_abbr) or pd.isna(serial):
                continue
            if isinstance(serial, datetime):
                date = serial
            else:
                try:
                    date = base + timedelta(days=float(serial))
                except:
                    continue
            for col in range(2, df.shape[1]):
                cell = df.iloc[row_idx, col]
                if isinstance(cell, str) and user_name in cell:
                    point = points.get(col, "Неизвестно")
                    shift_str = f"{day_abbr}, {date.day} {month_genitive.get(month_sheet, month_sheet.lower())}: {point}"
                    shifts.append(shift_str)
        return shifts
    except Exception as e:
        logging.error(f"Ошибка табеля: {e}")
        return []

# Напоминания
def send_reminders():
    try:
        response = requests.get(EXCEL_URL)
        if response.status_code != 200:
            return
        df_emp = pd.read_excel(io.BytesIO(response.content), sheet_name="Список сотрудников", engine='openpyxl')
        name_to_id = {}
        for i in range(len(df_emp)):
            name = str(df_emp.iloc[i, 0]).strip()
            tid = df_emp.iloc[i, 1]
            if pd.notna(tid):
                name_to_id[name] = int(tid)

        tomorrow = datetime.now() + timedelta(days=1)
        month_names = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь']
        month_sheet = month_names[tomorrow.month - 1]
        month_genitive = {
            'Январь': 'января', 'Февраль': 'февраля', 'Март': 'марта', 'Апрель': 'апреля',
            'Май': 'мая', 'Июнь': 'июня', 'Июль': 'июля', 'Август': 'августа',
            'Сентябрь': 'сентября', 'Октябрь': 'октября', 'Ноябрь': 'ноября', 'Декабрь': 'декабря'
        }
        base = datetime(1899, 12, 30)
        serial_tomorrow = (tomorrow - base).days

        response = requests.get(TABEL_URL)
        if response.status_code != 200:
            return
        df_tabel = pd.read_excel(io.BytesIO(response.content), sheet_name=month_sheet, engine='openpyxl', header=None, parse_dates=False)
        header = df_tabel.iloc[0]
        points = {}
        current_point = None
        for col in range(2, df_tabel.shape[1]):
            if pd.notna(header[col]):
                current_point = header[col]
            if current_point:
                points[col] = current_point

        shift_row = None
        for r in range(1, df_tabel.shape[0]):
            s = df_tabel.iloc[r, 1]
            if isinstance(s, (int, float)) and int(s) == serial_tomorrow:
                shift_row = r
                break
        if shift_row is None:
            return

        for col in range(2, df_tabel.shape[1]):
            cell = df_tabel.iloc[shift_row, col]
            if isinstance(cell, str) and cell.strip():
                name = cell.strip()
                point = points.get(col, "Неизвестно")
                tid = name_to_id.get(name)
                if tid:
                    msg = f"*Напоминание:* завтра \\({tomorrow.day} {month_genitive.get(month_sheet)}\\) смена в {escape_markdown(point)}\\. 📅"
                    bot.send_message(tid, msg, parse_mode='MarkdownV2')
    except Exception as e:
        logging.error(f"Ошибка напоминаний: {e}")

# Меню
def get_main_menu_markup(registered):
    markup = InlineKeyboardMarkup(row_width=2)
    if not registered:
        markup.add(InlineKeyboardButton("Зарегистрироваться ✅", callback_data="register"))
    else:
        markup.add(
            InlineKeyboardButton("Моя зарплата 💰", callback_data="salary"),
            InlineKeyboardButton("Мой табель 📅", callback_data="tabel")
        )
    markup.add(InlineKeyboardButton("Заполнить форму 📝", url="https://docs.google.com/forms/u/0/d/e/1FAIpQLSdt4Xl89HwFdwWvGSzCxBh0zh-i2lQNcELEJYfspkyxmzGIsw/formResponse"))
    return markup

def get_month_menu_markup():
    markup = InlineKeyboardMarkup(row_width=3)
    markup.add(
        InlineKeyboardButton("Октябрь", callback_data="month_Октябрь"),
        InlineKeyboardButton("Ноябрь", callback_data="month_Ноябрь"),
        InlineKeyboardButton("Декабрь", callback_data="month_Декабрь")
    )
    markup.add(InlineKeyboardButton("Назад 🔙", callback_data="back_to_menu"))
    return markup

# /start
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    registered, name = is_registered(user_id)
    welcome_msg = f"*Добро пожаловать{', ' + escape_markdown(name) + '!' if registered else '!'}*\\n\\nВыберите действие ниже\\. 😊"
    bot.send_message(message.chat.id, welcome_msg, parse_mode='MarkdownV2', reply_markup=get_main_menu_markup(registered))

# Колбэки
@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    user_id = call.from_user.id
    registered, name = is_registered(user_id)

    if call.data == "register":
        if registered:
            bot.answer_callback_query(call.id, "Вы уже зарегистрированы!")
            return
        user_states[user_id] = "waiting_for_name"
        bot.answer_callback_query(call.id)
        bot.send_message(user_id, "*Введите ваше имя:* ✍️", parse_mode='MarkdownV2')

    elif call.data == "salary":
        if not registered:
            bot.answer_callback_query(call.id, "Сначала зарегистрируйтесь!")
            return
        bot.answer_callback_query(call.id)
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="*Выберите месяц:* 📅",
            parse_mode='MarkdownV2',
            reply_markup=get_month_menu_markup()
        )

    elif call.data == "tabel":
        if not registered:
            bot.answer_callback_query(call.id, "Вы не зарегистрированы!")
            return
        bot.answer_callback_query(call.id)
        current_month = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'][datetime.now().month - 1]
        shifts = get_tabel_data(name, current_month)
        tabel_msg = f"*Ваши смены за {current_month}:*\\n\\n" + "\\n".join(f"\\- {escape_markdown(s)}" for s in shifts) if shifts else f"*Нет смен в {current_month}\\.* 😔"
        bot.send_message(call.message.chat.id, tabel_msg, parse_mode='MarkdownV2')
        welcome_msg = f"*Добро пожаловать, {escape_markdown(name)}\\!*\n\nВыберите действие\\. 😊"
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=welcome_msg,
            parse_mode='MarkdownV2',
            reply_markup=get_main_menu_markup(True)
        )

    elif call.data.startswith("month_"):
        month = call.data.split("_")[1]
        bot.answer_callback_query(call.id)
        data = get_salary_data(month, user_id)
        if data[0] is None:
            salary_msg = "*Данные не найдены\\.* 😔"
        else:
            n, h1, h2, th, a1, a2, ts = data
            salary_msg = f"**{escape_markdown(n)} за {month}:**\\n\\n" \
                         f"⏰ *1 пол:* {h1}\\n⏰ *2 пол:* {h2}\\n⏱️ *Всего:* {th}\\n\\n" \
                         f"💰 *Аванс 1:* {a1}\\n💰 *Аванс 2:* {a2}\\n💵 *Итого:* {ts} руб\\. 🎉"
        bot.send_message(call.message.chat.id, salary_msg, parse_mode='MarkdownV2')
        welcome_msg = f"*Добро пожаловать, {escape_markdown(name)}\\!*\n\nВыберите действие\\. 😊"
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=welcome_msg,
            parse_mode='MarkdownV2',
            reply_markup=get_main_menu_markup(True)
        )

    elif call.data == "back_to_menu":
        bot.answer_callback_query(call.id)
        welcome_msg = f"*Добро пожаловать{', ' + escape_markdown(name) + '!' if registered else '!'}*\\n\\nВыберите действие\\. 😊"
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=welcome_msg,
            parse_mode='MarkdownV2',
            reply_markup=get_main_menu_markup(registered)
        )

    elif call.data.startswith("confirm_") or call.data.startswith("reject_"):
        if user_id != ADMIN_ID:
            bot.answer_callback_query(call.id, "Только админ!")
            return
        target_id = int(call.data.split("_")[1])
        action = "подтверждена" if "confirm" in call.data else "отклонена"
        bot.answer_callback_query(call.id, f"{action.capitalize()}!")
        bot.edit_message_reply_markup(chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=None)
        bot.send_message(target_id, f"*Регистрация {action}\\!* {'🎉' if action == 'подтверждена' else 'Попробуйте снова 😔'}", parse_mode='MarkdownV2')
        if "confirm" in call.data:
            reg, n = is_registered(target_id)
            if reg:
                welcome = f"*Добро пожаловать, {escape_markdown(n)}\\!*\n\nДоступ открыт\\."
                bot.send_message(target_id, welcome, parse_mode='MarkdownV2', reply_markup=get_main_menu_markup(True))
        if target_id in pending_users:
            del pending_users[target_id]

# Текст (регистрация)
@bot.message_handler(func=lambda message: True)
def handle_text(message):
    user_id = message.from_user.id
    if user_states.get(user_id) == "waiting_for_name":
        name = message.text.strip()
        username = message.from_user.username or "Не указан"
        pending_users[user_id] = name
        bot.send_message(user_id, "*Заявка отправлена\\! Ожидайте\\.* 🎉", parse_mode='MarkdownV2')
        admin_msg = f"*Новая регистрация!*\n\n*Имя:* {escape_markdown(name)}\n*Username:* @{escape_markdown(username)}\n*ID:* `{user_id}`"
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("Подтвердить ✅", callback_data=f"confirm_{user_id}"),
            InlineKeyboardButton("Отклонить ❌", callback_data=f"reject_{user_id}")
        )
        bot.send_message(ADMIN_ID, admin_msg, parse_mode='MarkdownV2', reply_markup=markup)
        del user_states[user_id]

# Webhook
app = flask.Flask(__name__)

@app.route('/', methods=['GET', 'HEAD'])
def index():
    return ''

@app.route('/', methods=['POST'])
def webhook():
    if flask.request.headers.get('content-type') == 'application/json':
        update = telebot.types.Update.de_json(flask.request.get_data().decode('utf-8'))
        bot.process_new_updates([update])
        return ''
    flask.abort(403)

if __name__ == '__main__':
    bot.remove_webhook()
    bot.set_webhook(url='https://telegram-bot-1-ydll.onrender.com')
    scheduler = BackgroundScheduler(timezone="Europe/Moscow")
    scheduler.add_job(send_reminders, 'cron', hour=20, minute=0)
    scheduler.start()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))