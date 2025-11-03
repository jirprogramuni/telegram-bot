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
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Токен бота и ID админа
BOT_TOKEN = '7478861606:AAF-7eV0XjTn7S_6Q_caIk7Y27kGsfU_f-A'
ADMIN_ID = 476747112
bot = telebot.TeleBot(BOT_TOKEN)

# Глобальные кэши
user_cache = {}  # user_id -> (registered, name, timestamp)
salary_cache = {}  # (user_id, month) -> data
CACHE_TTL = 300  # 5 минут

# URL для экспорта
EXCEL_URL = 'https://docs.google.com/spreadsheets/d/1SsG4uRtpslwSeZFZsIjWOAesrHvT6WhxrNoCgYRTUfg/export?format=xlsx'
TABEL_URL = 'https://docs.google.com/spreadsheets/d/1q6Rqx3ypWYZAD74MdH-iz-tN5aAANrnDglLysvHg9_8/export?format=xlsx'

# Google Sheets API
SCOPE = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
CREDS_FILE = 'credentials.json'
creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
client = gspread.authorize(creds)
SHEET_ID = '1SsG4uRtpslwSeZFZsIjWOAesrHvT6WhxrNoCgYRTUfg'
sheet = client.open_by_key(SHEET_ID)

# Словарь состояний
user_states = {}
pending_users = {}

# Путь к фото
photo_path = 'photo_2025-10-28_01-49-34.jpg'


# === КЭШИРОВАННАЯ ПРОВЕРКА РЕГИСТРАЦИИ ===
def is_registered(user_id):
    now = datetime.now().timestamp()
    if user_id in user_cache:
        registered, name, ts = user_cache[user_id]
        if now - ts < CACHE_TTL:
            logging.info(f"КЭШ: is_registered({user_id}) -> {registered}, {name}")
            return registered, name

    logging.info(f"Запрос к Google Sheets: проверка is_registered({user_id})")
    try:
        ws = sheet.worksheet("Список сотрудников")
        data = ws.get_all_values()
        if not data:
            user_cache[user_id] = (False, None, now)
            return False, None

        for row in data[1:]:  # Пропустить заголовок
            if len(row) > 1 and str(row[1]).strip() == str(user_id):
                name = str(row[0]).strip()
                user_cache[user_id] = (True, name, now)
                logging.info(f"Успешно: {user_id} -> {name}")
                return True, name

        user_cache[user_id] = (False, None, now)
        return False, None

    except Exception as e:
        logging.error(f"Ошибка is_registered: {e}")
    user_cache[user_id] = (False, None, now)
    return False, None


# === КЭШИРОВАННЫЕ ДАННЫЕ ЗАРПЛАТЫ ===
def get_salary_data(month_sheet, telegram_id):
    cache_key = (telegram_id, month_sheet)
    now = datetime.now().timestamp()
    if cache_key in salary_cache:
        data, ts = salary_cache[cache_key]
        if now - ts < CACHE_TTL:
            return data

    logging.info(f"Запрос зарплаты: {month_sheet} для {telegram_id}")
    try:
        ws = sheet.worksheet(month_sheet)
        data = ws.get_all_values()
        if not data or len(data) < 2:
            salary_cache[cache_key] = ((None,) * 7, now)
            return (None,) * 7

        headers = data[0]
        for row in data[1:]:
            if len(row) > 1 and str(row[1]).strip() == str(telegram_id):
                name = str(row[0]).strip()
                hours_first = float(row[headers.index('Общие часы 1 половина')]) if 'Общие часы 1 половина' in headers else 0
                hours_second = float(row[headers.index('Общие часы 2 половина')]) if 'Общие часы 2 половина' in headers else 0
                total_hours = hours_first + hours_second
                first_advance = float(row[headers.index('Депозит 1')]) if 'Депозит 1' in headers else 0
                second_advance = float(row[headers.index('Депозит 2')]) if 'Депозит 2' in headers else 0
                total_salary = float(row[headers.index('Итоговая з/п')]) if 'Итоговая з/п' in headers else 0

                result = (name, hours_first, hours_second, total_hours, first_advance, second_advance, total_salary)
                salary_cache[cache_key] = (result, now)
                return result

        salary_cache[cache_key] = ((None,) * 7, now)
        return (None,) * 7

    except Exception as e:
        logging.error(f"Ошибка get_salary_data: {e}")
        salary_cache[cache_key] = ((None,) * 7, now)
        return (None,) * 7


# === ТАБЕЛЬ ===
def get_tabel_data(user_name, month_sheet):
    try:
        response = requests.get(TABEL_URL, timeout=10)
        if response.status_code != 200:
            return []

        file_like = io.BytesIO(response.content)
        df = pd.read_excel(file_like, sheet_name=month_sheet, engine='openpyxl', header=None, parse_dates=False)

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
        logging.error(f"Ошибка get_tabel_data: {e}")
        return []


# === НАПОМИНАНИЯ ===
def send_reminders():
    try:
        logging.info("Запуск напоминаний...")
        response = requests.get(EXCEL_URL, timeout=10)
        if response.status_code != 200:
            return
        df_emp = pd.read_excel(io.BytesIO(response.content), sheet_name="Список сотрудников", engine='openpyxl')
        name_to_id = {str(row[0]).strip(): int(row[1]) for _, row in df_emp.iterrows() if pd.notna(row[1])}

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

        response = requests.get(TABEL_URL, timeout=10)
        if response.status_code != 200:
            return
        df_tabel = pd.read_excel(io.BytesIO(response.content), sheet_name=month_sheet, engine='openpyxl', header=None)

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
            if pd.notna(s) and int(float(s)) == serial_tomorrow:
                shift_row = r
                break
        if not shift_row:
            return

        for col in range(2, df_tabel.shape[1]):
            cell = df_tabel.iloc[shift_row, col]
            if pd.notna(cell):
                name = str(cell).strip()
                tid = name_to_id.get(name)
                if tid:
                    point = points.get(col, "Неизвестно")
                    msg = f"*Напоминание:* завтра ({tomorrow.day} {month_genitive.get(month_sheet, month_sheet.lower())}) смена в *{point}*."
                    bot.send_message(tid, msg, parse_mode='Markdown')
    except Exception as e:
        logging.error(f"Ошибка в напоминаниях: {e}")


# === МЕНЮ ===
def get_main_menu_markup(registered):
    markup = InlineKeyboardMarkup(row_width=2)
    if not registered:
        markup.add(InlineKeyboardButton("Зарегистрироваться", callback_data="register"))
    else:
        markup.add(
            InlineKeyboardButton("Узнать зарплату", callback_data="salary"),
            InlineKeyboardButton("Мой табель", callback_data="tabel")
        )
        markup.add(InlineKeyboardButton("Заполнить форму", url="https://docs.google.com/forms/u/0/d/e/1FAIpQLSdt4Xl89HwFdwWvGSzCxBh0zh-i2lQNcELEJYfspkyxmzGIsw/formResponse"))
    return markup

def get_month_menu_markup():
    markup = InlineKeyboardMarkup(row_width=3)
    markup.add(
        InlineKeyboardButton("Октябрь", callback_data="month_Октябрь"),
        InlineKeyboardButton("Ноябрь", callback_data="month_Ноябрь"),
        InlineKeyboardButton("Декабрь", callback_data="month_Декабрь")
    )
    markup.add(InlineKeyboardButton("Назад", callback_data="back_to_menu"))
    return markup


# === ОБРАБОТЧИКИ ===
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    registered, name = is_registered(user_id)
    welcome_msg = f"*Добро пожаловать, {name}!*" if registered else "*Добро пожаловать!*"
    welcome_msg += "\n\nВыберите действие ниже."
    markup = get_main_menu_markup(registered)
    try:
        with open(photo_path, 'rb') as photo:
            bot.send_photo(message.chat.id, photo, caption=welcome_msg, parse_mode='Markdown', reply_markup=markup)
    except Exception as e:
        logging.error(f"Ошибка отправки фото: {e}")
        bot.send_message(message.chat.id, welcome_msg, parse_mode='Markdown', reply_markup=markup)


@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    user_id = call.from_user.id
    logging.info(f"Callback: {call.data} от {user_id}")

    registered, name = is_registered(user_id)

    try:
        if call.data == "register":
            if registered:
                bot.answer_callback_query(call.id, "Вы уже зарегистрированы!")
                return
            user_states[user_id] = "waiting_for_name"
            bot.answer_callback_query(call.id)
            bot.send_message(user_id, "*Введите ваше имя:*", parse_mode='Markdown')

        elif call.data == "salary":
            if not registered:
                bot.answer_callback_query(call.id, "Сначала зарегистрируйтесь!")
                return
            bot.answer_callback_query(call.id)  # МГНОВЕННЫЙ ОТВЕТ
            bot.edit_message_text(
                "*Выберите месяц:*",
                call.message.chat.id,
                call.message.message_id,
                parse_mode='Markdown',
                reply_markup=get_month_menu_markup()
            )

        elif call.data == "tabel":
            if not registered:
                bot.answer_callback_query(call.id, "Сначала зарегистрируйтесь!")
                return
            bot.answer_callback_query(call.id)
            month_names = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь']
            current_month = month_names[datetime.now().month - 1]
            shifts = get_tabel_data(name, current_month)
            msg = f"**Ваши смены за {current_month}:**\n\n" + "\n".join([f"- {s}" for s in shifts]) if shifts else f"*Нет смен в {current_month.lower()}*"
            bot.send_message(call.message.chat.id, msg, parse_mode='Markdown')
            send_main_menu(call.message.chat.id, registered, name)

        elif call.data.startswith("month_"):
            month = call.data.split("_")[1]
            bot.answer_callback_query(call.id)
            data = get_salary_data(month, user_id)
            if data[0] is None:
                msg = "*Данные не найдены*"
            else:
                n, h1, h2, th, a1, a2, ts = data
                msg = f"**Зарплата за {month}:**\n\n" \
                      f"**Имя:** {n}\n" \
                      f"**1 половина:** {h1} ч\n" \
                      f"**2 половина:** {h2} ч\n" \
                      f"**Всего:** {th} ч\n\n" \
                      f"**Аванс 1:** {a1} руб.\n" \
                      f"**Аванс 2:** {a2} руб.\n" \
                      f"**Итого:** {ts} руб."
            bot.send_message(call.message.chat.id, msg, parse_mode='Markdown')
            send_main_menu(call.message.chat.id, registered, name)

        elif call.data == "back_to_menu":
            bot.answer_callback_query(call.id)
            send_main_menu(call.message.chat.id, registered, name)

        elif call.data.startswith(("confirm_", "reject_")):
            if user_id != ADMIN_ID:
                bot.answer_callback_query(call.id, "Только админ!")
                return
            action, uid = call.data.split("_")
            uid = int(uid)
            if action == "confirm" and uid in pending_users:
                bot.answer_callback_query(call.id, "Подтверждено!")
                bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
                bot.send_message(uid, "*Регистрация подтверждена!*", parse_mode='Markdown')
                del pending_users[uid]
                reg, n = is_registered(uid)
                if reg:
                    send_main_menu(uid, True, n)
            elif action == "reject" and uid in pending_users:
                bot.answer_callback_query(call.id, "Отклонено!")
                bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
                bot.send_message(uid, "*Регистрация отклонена*", parse_mode='Markdown')
                del pending_users[uid]

    except Exception as e:
        logging.error(f"Ошибка в callback: {e}")
        bot.answer_callback_query(call.id, "Ошибка, попробуйте позже")


def send_main_menu(chat_id, registered, name=None):
    msg = f"*Добро пожаловать, {name}!*" if registered else "*Добро пожаловать!*"
    msg += "\n\nВыберите действие ниже."
    markup = get_main_menu_markup(registered)
    try:
        with open(photo_path, 'rb') as photo:
            bot.send_photo(chat_id, photo, caption=msg, parse_mode='Markdown', reply_markup=markup)
    except:
        bot.send_message(chat_id, msg, parse_mode='Markdown', reply_markup=markup)


@bot.message_handler(func=lambda m: True)
def handle_text(message):
    user_id = message.from_user.id
    if user_states.get(user_id) == "waiting_for_name":
        name = message.text.strip()
        username = message.from_user.username or "Не указан"
        pending_users[user_id] = name
        bot.send_message(user_id, f"*Заявка отправлена!*\nОжидайте подтверждения.", parse_mode='Markdown')

        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("Подтвердить", callback_data=f"confirm_{user_id}"),
            InlineKeyboardButton("Отклонить", callback_data=f"reject_{user_id}")
        )
        bot.send_message(ADMIN_ID, f"*Новая заявка!*\nИмя: {name}\n@{username}\nID: {user_id}", parse_mode='Markdown', reply_markup=markup)
        del user_states[user_id]


# === FLASK WEBHOOK ===
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
    return 'Forbidden', 403


if __name__ == '__main__':
    bot.remove_webhook()
    bot.set_webhook(url='https://telegram-bot-1-ydll.onrender.com')

    scheduler = BackgroundScheduler(timezone="Europe/Moscow")
    scheduler.add_job(send_reminders, 'cron', hour=20, minute=0)
    scheduler.start()

    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)