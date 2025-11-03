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

# === НАСТРОЙКА ЛОГИРОВАНИЯ ===
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# === КОНФИГИ ===
BOT_TOKEN = '7478861606:AAF-7eV0XjTn7S_6Q_caIk7Y27kGsfU_f-A'
ADMIN_ID = 476747112
bot = telebot.TeleBot(BOT_TOKEN)

# === КЭШИ ===
user_cache = {}  # user_id -> (registered, name, timestamp)
salary_cache = {}  # (user_id, month) -> (data, timestamp)
CACHE_TTL = 300  # 5 минут

# === URL ДЛЯ ЭКСПОРТА ===
EXCEL_URL = 'https://docs.google.com/spreadsheets/d/1SsG4uRtpslwSeZFZsIjWOAesrHvT6WhxrNoCgYRTUfg/export?format=xlsx'
TABEL_URL = 'https://docs.google.com/spreadsheets/d/1q6Rqx3ypWYZAD74MdH-iz-tN5aAANrnDglLysvHg9_8/export?format=xlsx'

# === Google Sheets API (только для админа, если нужно) ===
SCOPE = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
CREDS_FILE = 'credentials.json'
if os.path.exists(CREDS_FILE):
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
    client = gspread.authorize(creds)
    SHEET_ID = '1SsG4uRtpslwSeZFZsIjWOAesrHvT6WhxrNoCgYRTUfg'
    sheet = client.open_by_key(SHEET_ID)
else:
    sheet = None
    logging.warning("credentials.json не найден — админские функции отключены")

# === СЛОВАРЬ СОСТОЯНИЙ ===
user_states = {}
pending_users = {}

# === ПУТЬ К ФОТО ===
photo_path = 'photo_2025-10-28_01-49-34.jpg'

# === ПРОВЕРКА РЕГИСТРАЦИИ (КЭШ) ===
def is_registered(user_id):
    now = datetime.now().timestamp()
    if user_id in user_cache:
        registered, name, ts = user_cache[user_id]
        if now - ts < CACHE_TTL:
            logging.info(f"КЭШ: is_registered({user_id}) -> {registered}, {name}")
            return registered, name

    logging.info(f"Запрос к Google Sheets: проверка is_registered({user_id})")
    try:
        response = requests.get(EXCEL_URL, timeout=15)
        if response.status_code != 200:
            logging.error(f"Ошибка загрузки файла: {response.status_code}")
            user_cache[user_id] = (False, None, now)
            return False, None

        file_like = io.BytesIO(response.content)
        df = pd.read_excel(file_like, sheet_name="Список сотрудников", engine='openpyxl')
        df.columns = df.columns.str.strip()

        if len(df.columns) < 2:
            user_cache[user_id] = (False, None, now)
            return False, None

        row = df[df.iloc[:, 1].astype(str).str.strip() == str(user_id)]
        if row.empty:
            user_cache[user_id] = (False, None, now)
            return False, None

        name = str(row.iloc[0, 0]).strip()
        user_cache[user_id] = (True, name, now)
        logging.info(f"Успешно: {user_id} -> {name}")
        return True, name

    except Exception as e:
        logging.error(f"Ошибка is_registered: {e}", exc_info=True)
        user_cache[user_id] = (False, None, now)
        return False, None

# === ПОЛУЧЕНИЕ ДАННЫХ ЗАРПЛАТЫ (ГИБКИЙ ПОИСК КОЛОНОК) ===
def get_salary_data(month_sheet, telegram_id):
    cache_key = (telegram_id, month_sheet)
    now = datetime.now().timestamp()
    if cache_key in salary_cache:
        data, ts = salary_cache[cache_key]
        if now - ts < CACHE_TTL:
            return data

    logging.info(f"Запрос зарплаты: {month_sheet} для {telegram_id}")
    try:
        response = requests.get(EXCEL_URL, timeout=15)
        if response.status_code != 200:
            salary_cache[cache_key] = ((None,) * 7, now)
            return (None,) * 7

        file_like = io.BytesIO(response.content)
        xls = pd.ExcelFile(file_like, engine='openpyxl')

        if month_sheet not in xls.sheet_names:
            logging.warning(f"Лист '{month_sheet}' не найден")
            salary_cache[cache_key] = ((None,) * 7, now)
            return (None,) * 7

        df = pd.read_excel(file_like, sheet_name=month_sheet, engine='openpyxl')
        df.columns = df.columns.str.strip()

        # Поиск строки по ID
        row = df[df.iloc[:, 1].astype(str).str.strip() == str(telegram_id)]
        if row.empty:
            salary_cache[cache_key] = ((None,) * 7, now)
            return (None,) * 7

        name = str(row.iloc[0, 0]).strip()

        # Гибкий поиск колонок
        def find_col(patterns):
            for col in df.columns:
                if any(p.lower() in str(col).lower() for p in patterns):
                    return col
            return None

        h1_col = find_col(['общие часы 1', 'часы 1 половина', '1 половина', 'часы 1'])
        h2_col = find_col(['общие часы 2', 'часы 2 половина', '2 половина', 'часы 2'])
        a1_col = find_col(['депозит 1', 'аванс 1', '1 аванс'])
        a2_col = find_col(['депозит 2', 'аванс 2', '2 аванс'])
        total_col = find_col(['итоговая з/п', 'итого', 'зп итог', 'зарплата', 'к выплате'])

        hours_first = float(row.iloc[0, df.columns.get_loc(h1_col)]) if h1_col else 0.0
        hours_second = float(row.iloc[0, df.columns.get_loc(h2_col)]) if h2_col else 0.0
        total_hours = hours_first + hours_second
        first_advance = float(row.iloc[0, df.columns.get_loc(a1_col)]) if a1_col else 0.0
        second_advance = float(row.iloc[0, df.columns.get_loc(a2_col)]) if a2_col else 0.0
        total_salary = float(row.iloc[0, df.columns.get_loc(total_col)]) if total_col else 0.0

        result = (name, hours_first, hours_second, total_hours, first_advance, second_advance, total_salary)
        salary_cache[cache_key] = (result, now)
        logging.info(f"Зарплата загружена: {name}, {total_salary} руб.")
        return result

    except Exception as e:
        logging.error(f"Ошибка get_salary_data: {e}", exc_info=True)
        salary_cache[cache_key] = ((None,) * 7, now)
        return (None,) * 7

# === ТАБЕЛЬ ===
def get_tabel_data(user_name, month_sheet):
    try:
        response = requests.get(TABEL_URL, timeout=15)
        if response.status_code != 200:
            return []
        file_like = io.BytesIO(response.content)
        df = pd.read_excel(file_like, sheet_name=month_sheet, engine='openpyxl', header=None)
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
            try:
                if isinstance(serial, datetime):
                    date = serial
                else:
                    date = base + timedelta(days=float(serial))
            except:
                continue
            for col in range(2, df.shape[1]):
                cell = df.iloc[row_idx, col]
                if pd.notna(cell) and user_name in str(cell):
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
        response = requests.get(EXCEL_URL, timeout=15)
        if response.status_code != 200:
            return
        df_emp = pd.read_excel(io.BytesIO(response.content), sheet_name="Список сотрудников", engine='openpyxl')
        name_to_id = {str(row[0]).strip(): int(row[1]) for _, row in df_emp.iterrows() if pd.notna(row[1])}

        tomorrow = datetime.now() + timedelta(days=1)
        month_names = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь']
        month_sheet = month_names[tomorrow.month - 1]

        response = requests.get(TABEL_URL, timeout=15)
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

        base = datetime(1899, 12, 30)
        serial_tomorrow = (tomorrow - base).days
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
                    msg = f"*Напоминание:* завтра ({tomorrow.day} {month_genitive.get(month_sheet, '')}) смена в *{point}*."
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
    now = datetime.now()
    buttons = []
    for i in range(2, -1, -1):
        date = now - timedelta(days=30 * i)
        month_name = ['Январь','Февраль','Март','Апрель','Май','Июнь',
                      'Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь'][date.month - 1]
        buttons.append(InlineKeyboardButton(month_name, callback_data=f"month_{month_name}"))
    markup.add(*buttons)
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
            bot.answer_callback_query(call.id)
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
            month_names = ['Январь','Февраль','Март','Апрель','Май','Июнь','Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь']
            current_month = month_names[datetime.now().month - 1]
            shifts = get_tabel_data(name, current_month)
            msg = f"*Ваши смены за {current_month}:*\n\n" + "\n".join([f"• {s}" for s in shifts]) if shifts else f"*Нет смен в {current_month.lower()}*"
            bot.send_message(call.message.chat.id, msg, parse_mode='Markdown')
            send_main_menu(call.message.chat.id, registered, name)

        elif call.data.startswith("month_"):
            month = call.data.split("_", 1)[1]
            bot.answer_callback_query(call.id)
            data = get_salary_data(month, user_id)
            if not data or data[0] is None:
                msg = "*Данные за этот месяц не найдены или ещё не заполнены.*"
            else:
                n, h1, h2, th, a1, a2, ts = data
                msg = f"*Зарплата за {month}:*\n\n" \
                      f"**Имя:** {n}\n" \
                      f"**1 половина:** {h1:.1f} ч\n" \
                      f"**2 половина:** {h2:.1f} ч\n" \
                      f"**Всего часов:** {th:.1f} ч\n\n" \
                      f"**Аванс 1:** {a1:,.0f} ₽\n" \
                      f"**Аванс 2:** {a2:,.0f} ₽\n" \
                      f"**Итого к выплате:** {ts:,.0f} ₽"
            bot.send_message(call.message.chat.id, msg, parse_mode='Markdown')
            send_main_menu(call.message.chat.id, registered, name)

        elif call.data == "back_to_menu":
            bot.answer_callback_query(call.id)
            send_main_menu(call.message.chat.id, registered, name)

        elif call.data.startswith(("confirm_", "reject_")):
            if user_id != ADMIN_ID:
                bot.answer_callback_query(call.id, "Только админ!")
                return
            action, uid = call.data.split("_", 1)
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
        logging.error(f"Ошибка в callback: {e}", exc_info=True)
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
        json_string = flask.request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return ''
    return 'Forbidden', 403

# === ЗАПУСК ===
if __name__ == '__main__':
    bot.remove_webhook()
    bot.set_webhook(url='https://telegram-bot-1-ydll.onrender.com')

    scheduler = BackgroundScheduler(timezone="Europe/Moscow")
    scheduler.add_job(send_reminders, 'cron', hour=20, minute=0)
    scheduler.start()

    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)