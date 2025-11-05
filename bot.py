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
import zoneinfo
import calendar

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Токен бота и ID админа
BOT_TOKEN = '7478861606:AAF-7eV0XjTn7S_6Q_caIk7Y27kGsfU_f-A'
ADMIN_ID = 476747112
bot = telebot.TeleBot(BOT_TOKEN)

# Состояния и данные
user_states = {}
pending_users = {}
shift_data = {}  # {user_id: {date, point, time_in, time_out, total_hours}}

# Заведения
WORK_POINTS = [
    "КУЧИНО",
    "РЕУТОВ (Победы)",
    "ЛЕНИНА",
    "НЯМС",
    "РЕУТОВ (Юбилейный)"
]

# URL для экспорта Google Sheets в формате XLSX
EXCEL_URL = 'https://docs.google.com/spreadsheets/d/1SsG4uRtpslwSeZFZsIjWOAesrHvT6WhxrNoCgYRTUfg/export?format=xlsx'
TABEL_URL = 'https://docs.google.com/spreadsheets/d/1q6Rqx3ypWYZAD74MdH-iz-tN5aAANrnDglLysvHg9_8/export?format=xlsx'

# Для записи в Google Sheets
SCOPE = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
CREDS_FILE = 'credentials.json'
creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
client = gspread.authorize(creds)
SHEET_ID = '1SsG4uRtpslwSeZFZsIjWOAesrHvT6WhxrNoCgYRTUfg'
sheet = client.open_by_key(SHEET_ID)

# Helper to escape special chars for MarkdownV2
def escape_md_v2(text):
    if not text:
        return ""
    special_chars = r'_*[]()~`>#+-=|{}.!'
    return ''.join(['\\' + char if char in special_chars else char for char in str(text)])

# === НОВЫЕ ФУНКЦИИ ===
def shift_exists(telegram_id, date_str):
    try:
        worksheet = client.open_by_key(SHEET_ID).worksheet("Сырые ответы формы ТГ")
        records = worksheet.get_all_records()
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        formatted_date = date_obj.strftime("%d.%m.%Y")
        for rec in records:
            if str(rec.get('Telegram ID', '')) == str(telegram_id) and rec.get('Дата смены', '') == formatted_date:
                return True
        return False
    except Exception as e:
        logging.error(f"Ошибка проверки смены: {e}")
        return False

def has_edit_permission(telegram_id, date_str):
    try:
        worksheet = client.open_by_key(SHEET_ID).worksheet("Разрешения")
        records = worksheet.get_all_records()
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        formatted_date = date_obj.strftime("%d.%m.%Y")
        for rec in records:
            if str(rec.get('Telegram ID', '')) == str(telegram_id) and \
               rec.get('Дата смены', '') == formatted_date and \
               rec.get('Статус', '') == "активно":
                return True
        return False
    except Exception as e:
        logging.error(f"Ошибка проверки разрешения: {e}")
        return False

def grant_edit_permission(telegram_id, date_str):
    try:
        worksheet = client.open_by_key(SHEET_ID).worksheet("Разрешения")
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        formatted_date = date_obj.strftime("%d.%m.%Y")
        worksheet.append_row([telegram_id, formatted_date, "активно"])
        return True
    except Exception as e:
        logging.error(f"Ошибка выдачи разрешения: {e}")
        return False

def save_shift_to_sheet(telegram_id, username, date_str, point, time_in, time_out, total_hours, status="Зафиксировано"):
    try:
        worksheet = client.open_by_key(SHEET_ID).worksheet("Сырые ответы формы ТГ")
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        formatted_date = date_obj.strftime("%d.%m.%Y")
        safe_username = f"@{username}" if username else ""
        worksheet.append_row([
            safe_username,
            telegram_id,
            formatted_date,
            point,
            time_in,
            time_out,
            total_hours,
            status
        ])
        return True
    except Exception as e:
        logging.error(f"Ошибка записи смены: {e}")
        return False

def generate_calendar(year, month):
    markup = InlineKeyboardMarkup()
    month_name = calendar.month_name[month].capitalize()
    markup.add(InlineKeyboardButton(f"{month_name} {year}", callback_data="ignore"))
    week_days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    markup.row(*[InlineKeyboardButton(day, callback_data="ignore") for day in week_days])
    cal = calendar.monthcalendar(year, month)
    for week in cal:
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(" ", callback_data="ignore"))
            else:
                row.append(InlineKeyboardButton(str(day), callback_data=f"date_{year}-{month:02d}-{day:02d}"))
        markup.row(*row)
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1
    markup.row(
        InlineKeyboardButton("◀️", callback_data=f"cal_{prev_year}_{prev_month}"),
        InlineKeyboardButton("Назад 🔙", callback_data="back_to_menu"),
        InlineKeyboardButton("▶️", callback_data=f"cal_{next_year}_{next_month}")
    )
    return markup

# === СТАРЫЕ ФУНКЦИИ (без изменений) ===
def is_registered(user_id):
    try:
        response = requests.get(EXCEL_URL)
        if response.status_code != 200:
            logging.error(f"Ошибка загрузки файла: {response.status_code}")
            return False, None
        file_like = io.BytesIO(response.content)
        df = pd.read_excel(file_like, sheet_name="Список сотрудников", engine='openpyxl')
        row = df[df.iloc[:, 1] == user_id]
        if row.empty:
            return False, None
        name = row.iloc[0, 0]
        return True, name
    except Exception as e:
        logging.error(f"Ошибка проверки регистрации: {e}")
        return False, None

def add_to_sheet(name, user_id):
    try:
        worksheet = sheet.worksheet("Список сотрудников")
        worksheet.append_row([name, user_id])
        return True
    except Exception as e:
        logging.error(f"Ошибка добавления в sheet: {e}")
        return False

def get_salary_data(month_sheet, telegram_id):
    try:
        registered, name = is_registered(telegram_id)
        if not registered:
            return None, None, None, None, None, None, None
        response = requests.get(EXCEL_URL)
        if response.status_code != 200:
            logging.error(f"Ошибка загрузки файла: {response.status_code}")
            return None, None, None, None, None, None, None
        file_like = io.BytesIO(response.content)
        df = pd.read_excel(file_like, sheet_name=month_sheet, engine='openpyxl')
        row = df[df.iloc[:, 0] == name]
        if row.empty:
            return None, None, None, None, None, None, None
        columns = df.columns
        hours_first_col = columns.get_loc('Общие часы 1 половина') if 'Общие часы 1 половина' in columns else None
        hours_second_col = columns.get_loc('Общие часы 2 половина') if 'Общие часы 2 половина' in columns else None
        first_advance_col = columns.get_loc('Депозит 1') if 'Депозит 1' in columns else None
        second_advance_col = columns.get_loc('Депозит 2') if 'Депозит 2' in columns else None
        total_salary_col = columns.get_loc('Итоговая з/п') if 'Итоговая з/п' in columns else None
        hours_first = row.iloc[0, hours_first_col] if hours_first_col is not None else 0
        hours_second = row.iloc[0, hours_second_col] if hours_second_col is not None else 0
        total_hours = hours_first + hours_second
        first_advance = row.iloc[0, first_advance_col] if first_advance_col is not None else 0
        second_advance = row.iloc[0, second_advance_col] if second_advance_col is not None else 0
        total_salary = row.iloc[0, total_salary_col] if total_salary_col is not None else 0
        return name, hours_first, hours_second, total_hours, first_advance, second_advance, total_salary
    except Exception as e:
        logging.error(f"Ошибка чтения данных: {e}")
        return None, None, None, None, None, None, None

def get_tabel_data(user_name, month_sheet):
    try:
        response = requests.get(TABEL_URL)
        if response.status_code != 200:
            logging.error(f"Ошибка загрузки табеля: {response.status_code}")
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
            if pd.isna(day_abbr):
                continue
            serial = df.iloc[row_idx, 1]
            if pd.isna(serial):
                continue
            if isinstance(serial, datetime):
                date = serial
            else:
                try:
                    serial = float(serial)
                    date = base + timedelta(days=serial)
                except (ValueError, TypeError):
                    continue
            for col in range(2, df.shape[1]):
                cell = df.iloc[row_idx, col]
                if isinstance(cell, str) and user_name in cell:
                    point = points.get(col)
                    if point:
                        shift_str = f"{day_abbr}, {date.day} {month_genitive.get(month_sheet, month_sheet.lower())}: {point}"
                        shifts.append(shift_str)
        return shifts
    except Exception as e:
        logging.error(f"Ошибка чтения табеля: {e}")
        return []

def send_reminders():
    try:
        tz = zoneinfo.ZoneInfo("Europe/Moscow")
        now = datetime.now(tz=tz)
        tomorrow = now + timedelta(days=1)
        month_names = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь']
        month_sheet = month_names[tomorrow.month - 1]
        response = requests.get(EXCEL_URL)
        if response.status_code != 200:
            logging.error(f"Ошибка загрузки списка сотрудников: {response.status_code}")
            return
        file_like = io.BytesIO(response.content)
        df_emp = pd.read_excel(file_like, sheet_name="Список сотрудников", engine='openpyxl')
        name_to_id = {}
        for i in range(len(df_emp)):
            name = str(df_emp.iloc[i, 0]).strip()
            tid = df_emp.iloc[i, 1]
            if pd.notna(tid):
                name_to_id[name] = int(tid)
        month_genitive = {
            'Январь': 'января', 'Февраль': 'февраля', 'Март': 'марта', 'Апрель': 'апреля',
            'Май': 'мая', 'Июнь': 'июня', 'Июль': 'июля', 'Август': 'августа',
            'Сентябрь': 'сентября', 'Октябрь': 'октября', 'Ноябрь': 'ноября', 'Декабрь': 'декабря'
        }
        base = datetime(1899, 12, 30)
        serial_tomorrow = (tomorrow.date() - base.date()).days
        response = requests.get(TABEL_URL)
        if response.status_code != 200:
            logging.error(f"Ошибка загрузки табеля: {response.status_code}")
            return
        file_like = io.BytesIO(response.content)
        df_tabel = pd.read_excel(file_like, sheet_name=month_sheet, engine='openpyxl', header=None, parse_dates=False)
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
            if isinstance(s, datetime):
                serial_from_sheet = (s.date() - base.date()).days
                if serial_from_sheet == serial_tomorrow:
                    shift_row = r
                    break
            elif isinstance(s, (int, float)):
                if int(s) == serial_tomorrow:
                    shift_row = r
                    break
        if shift_row is None:
            logging.info("Нет смен на завтра")
            return
        for col in range(2, df_tabel.shape[1]):
            cell = df_tabel.iloc[shift_row, col]
            if isinstance(cell, str) and cell.strip():
                name = cell.strip()
                point = points.get(col, "Неизвестно")
                tid = name_to_id.get(name)
                if tid:
                    msg = f"*Напоминание:* завтра ({tomorrow.day} {month_genitive.get(month_sheet, month_sheet.lower())}) у вас смена в {point}. 📅"
                    bot.send_message(tid, msg, parse_mode='Markdown')
                else:
                    logging.error(f"Нет ID для имени: {name}")
    except Exception as e:
        logging.error(f"Ошибка в отправке напоминаний: {e}")

def get_main_menu_markup(registered):
    from telebot.types import WebAppInfo
    markup = InlineKeyboardMarkup(row_width=2)
    if not registered:
        markup.add(InlineKeyboardButton("Зарегистрироваться ✅", callback_data="register"))
    else:
        markup.add(
            InlineKeyboardButton("Узнать зарплату 💰", callback_data="salary"),
            InlineKeyboardButton("Мой табель 📅", callback_data="tabel")
        )
        markup.add(
            InlineKeyboardButton("Записать смену 🕒", callback_data="log_shift")
        )
        markup.add(
            InlineKeyboardButton("Календарь смен (Мини-апп)", web_app=WebAppInfo(url="https://mini-app-wchu.onrender.com"))
        )
        markup.add(
            InlineKeyboardButton("Заполнить форму 📝", url="https://docs.google.com/forms/u/0/d/e/1FAIpQLSdt4Xl89HwFdwWvGSzCxBh0zh-i2lQNcELEJYfspkyxmzGIsw/formResponse")
        )
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

# === ОБРАБОТЧИКИ ===
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    registered, name = is_registered(user_id)
    welcome_msg = f"*Добро пожаловать, {name}!*\n\nВыберите действие ниже. 😊" if registered else "*Добро пожаловать!*\n\nВыберите действие ниже. 😊"
    markup = get_main_menu_markup(registered)
    bot.send_photo(
        message.chat.id,
        photo=open("photo_2025-10-28_01-49-34.jpg", "rb"),
        caption=welcome_msg,
        parse_mode='Markdown',
        reply_markup=markup
    )

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
        bot.send_message(user_id, "*Введите ваше имя:* ✍️", parse_mode='Markdown')

    elif call.data == "salary":
        if not registered:
            bot.answer_callback_query(call.id, "Вы не зарегистрированы!")
            return
        bot.answer_callback_query(call.id)
        bot.edit_message_caption(
            caption="*Выберите месяц для просмотра зарплаты:* 📅",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode='Markdown',
            reply_markup=get_month_menu_markup()
        )

    elif call.data == "tabel":
        if not registered:
            bot.answer_callback_query(call.id, "Вы не зарегистрированы!")
            return
        bot.answer_callback_query(call.id)
        tz = zoneinfo.ZoneInfo("Europe/Moscow")
        month_names = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь']
        current_month = month_names[datetime.now(tz=tz).month - 1]
        shifts = get_tabel_data(name, current_month)
        tabel_msg = f"**Ваши смены за {current_month}:** 📅\n\n" + "\n".join([f"- {shift}" for shift in shifts]) if shifts else f"*Нет смен в {current_month.lower()}.* 😔"
        bot.send_message(call.message.chat.id, tabel_msg, parse_mode='Markdown')
        welcome_msg = f"*Добро пожаловать, {name}!*\n\nВыберите действие ниже. 😊"
        markup = get_main_menu_markup(True)
        bot.edit_message_caption(
            caption=welcome_msg,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode='Markdown',
            reply_markup=markup
        )

    elif call.data.startswith("month_"):
        month = call.data.split("_")[1]
        bot.answer_callback_query(call.id)
        result = get_salary_data(month, user_id)
        if result[0] is None:
            salary_msg = "*Данные не найдены для вашего ID в этом месяце.* 😔"
        else:
            name, hours_first, hours_second, total_hours, first_advance, second_advance, total_salary = result
            salary_msg = f"*Ваша зарплата за {month}:* 💼\n\n" \
                         f"*Имя:* {name} 👤\n\n" \
                         f"*Отработано часов за 1 половину:* {hours_first} ⏰\n" \
                         f"*Отработано часов за 2 половину:* {hours_second} ⏰\n" \
                         f"*Всего часов:* {total_hours} ⏱️\n\n" \
                         f"*Первый аванс:* {first_advance} руб. 💰\n" \
                         f"*Второй аванс:* {second_advance} руб. 💰\n" \
                         f"*Итоговая з/п:* {total_salary} руб. 💵"
        bot.send_message(call.message.chat.id, salary_msg, parse_mode='Markdown')
        welcome_msg = f"*Добро пожаловать, {name}!*\n\nВыберите действие ниже. 😊"
        markup = get_main_menu_markup(True)
        bot.edit_message_caption(
            caption=welcome_msg,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode='Markdown',
            reply_markup=markup
        )

    elif call.data == "back_to_menu":
        bot.answer_callback_query(call.id)
        welcome_msg = f"*Добро пожаловать, {name}!*\n\nВыберите действие ниже. 😊" if registered else "*Добро пожаловать!*\n\nВыберите действие ниже. 😊"
        markup = get_main_menu_markup(registered)
        bot.edit_message_caption(
            caption=welcome_msg,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode='Markdown',
            reply_markup=markup
        )

    elif call.data == "log_shift":
        if not registered:
            bot.answer_callback_query(call.id, "Сначала зарегистрируйтесь!")
            return
        bot.answer_callback_query(call.id)
        now = datetime.now(zoneinfo.ZoneInfo("Europe/Moscow"))
        markup = generate_calendar(now.year, now.month)
        bot.edit_message_caption(
            caption="*Выберите дату смены:* 📅",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode='Markdown',
            reply_markup=markup
        )
        user_states[user_id] = "selecting_date"

    elif call.data.startswith("date_"):
        date_str = call.data.split("_", 1)[1]
        if shift_exists(user_id, date_str):
            if has_edit_permission(user_id, date_str):
                shift_data[user_id] = {"date": date_str}
                user_states[user_id] = "selecting_point"
                markup = InlineKeyboardMarkup(row_width=1)
                for point in WORK_POINTS:
                    markup.add(InlineKeyboardButton(point, callback_data=f"point_{point}"))
                markup.add(InlineKeyboardButton("Назад 🔙", callback_data="log_shift"))
                bot.edit_message_caption(
                    caption=f"*Выбрана дата:* {date_str}\n*Выберите заведение:*",
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    parse_mode='Markdown',
                    reply_markup=markup
                )
            else:
                markup = InlineKeyboardMarkup()
                markup.add(InlineKeyboardButton("✉️ Запросить изменение", callback_data=f"request_edit_{date_str}"))
                markup.add(InlineKeyboardButton("Назад 🔙", callback_data="log_shift"))
                bot.edit_message_caption(
                    caption=f"Смена на {date_str} уже зафиксирована.\nХотите запросить изменение?",
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    reply_markup=markup
                )
        else:
            shift_data[user_id] = {"date": date_str}
            user_states[user_id] = "selecting_point"
            markup = InlineKeyboardMarkup(row_width=1)
            for point in WORK_POINTS:
                markup.add(InlineKeyboardButton(point, callback_data=f"point_{point}"))
            markup.add(InlineKeyboardButton("Назад 🔙", callback_data="log_shift"))
            bot.edit_message_caption(
                caption=f"*Выбрана дата:* {date_str}\n*Выберите заведение:*",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode='Markdown',
                reply_markup=markup
            )

    elif call.data.startswith("cal_"):
        _, year, month = call.data.split("_")
        year, month = int(year), int(month)
        markup = generate_calendar(year, month)
        bot.edit_message_reply_markup(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=markup
        )

    elif call.data.startswith("point_"):
        point = call.data.split("_", 1)[1]
        if user_id not in shift_data:
            bot.answer_callback_query(call.id, "Ошибка: начните сначала.")
            return
        shift_data[user_id]["point"] = point
        user_states[user_id] = "entering_time_in"
        bot.send_message(user_id, "Время прихода (ЧЧ:ММ):")

    elif call.data == "confirm_shift":
        data = shift_data.get(user_id)
        if not data:
            bot.answer_callback_query(call.id, "Ошибка данных.")
            return
        username = call.from_user.username
        status = "Смена не защищена" if has_edit_permission(user_id, data["date"]) else "Зафиксировано"
        success = save_shift_to_sheet(
            user_id, username, data["date"], data["point"],
            data["time_in"], data["time_out"], data["total_hours"], status
        )
        if success:
            msg = "Смена зафиксирована!" if status == "Зафиксировано" else "Смена обновлена! (требует проверки)"
            bot.send_message(user_id, msg)
        else:
            bot.send_message(user_id, "Ошибка записи.")
        shift_data.pop(user_id, None)
        user_states.pop(user_id, None)
        welcome_msg = f"*Добро пожаловать, {name}!*\n\nВыберите действие ниже. 😊"
        markup = get_main_menu_markup(True)
        bot.edit_message_caption(
            caption=welcome_msg,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode='Markdown',
            reply_markup=markup
        )

    elif call.data.startswith("request_edit_"):
        date_str = call.data.split("_", 2)[2]
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("Разрешить", callback_data=f"allow_edit_{user_id}_{date_str}"),
            InlineKeyboardButton("Отклонить", callback_data=f"deny_edit_{user_id}_{date_str}")
        )
        bot.send_message(
            ADMIN_ID,
            f"Запрос на изменение смены:\nID: {user_id}\nДата: {date_str}\nИмя: {name}",
            reply_markup=markup
        )
        bot.answer_callback_query(call.id, "Запрос отправлен админу!")

    elif call.data.startswith("allow_edit_"):
        if call.from_user.id != ADMIN_ID:
            return
        _, target_user_id, date_str = call.data.split("_", 2)
        target_user_id = int(target_user_id)
        if grant_edit_permission(target_user_id, date_str):
            bot.send_message(target_user_id, f"Вам разрешено изменить смену на {date_str}.")
            bot.answer_callback_query(call.id, "Разрешено!")
        else:
            bot.answer_callback_query(call.id, "Ошибка.")
        bot.edit_message_reply_markup(chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=None)

    elif call.data.startswith("deny_edit_"):
        if call.from_user.id != ADMIN_ID:
            return
        _, target_user_id, date_str = call.data.split("_", 2)
        target_user_id = int(target_user_id)
        bot.send_message(target_user_id, f"Админ отклонил запрос на изменение смены на {date_str}.")
        bot.answer_callback_query(call.id, "Отклонено!")
        bot.edit_message_reply_markup(chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=None)

    elif call.data.startswith("confirm_"):
        if user_id != ADMIN_ID:
            bot.answer_callback_query(call.id, "Только админ!")
            return
        confirm_user_id = int(call.data.split("_")[1])
        confirm_name = pending_users.get(confirm_user_id)
        if confirm_name:
            bot.answer_callback_query(call.id, "Подтверждено!")
            bot.edit_message_reply_markup(chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=None)
            add_to_sheet(confirm_name, confirm_user_id)
            welcome_msg = f"*Добро пожаловать, {confirm_name}!*\n\nВыберите действие ниже. 😊"
            markup = get_main_menu_markup(True)
            bot.send_message(confirm_user_id, "*Регистрация подтверждена!*", parse_mode='Markdown')
            bot.send_photo(
                confirm_user_id,
                photo=open("photo_2025-10-28_01-49-34.jpg", "rb"),
                caption=welcome_msg,
                parse_mode='Markdown',
                reply_markup=markup
            )
            del pending_users[confirm_user_id]
        else:
            bot.answer_callback_query(call.id, "Пользователь не найден!")

    elif call.data.startswith("reject_"):
        if user_id != ADMIN_ID:
            bot.answer_callback_query(call.id, "Только админ!")
            return
        reject_user_id = int(call.data.split("_")[1])
        if reject_user_id in pending_users:
            bot.answer_callback_query(call.id, "Отклонено!")
            bot.edit_message_reply_markup(chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=None)
            bot.send_message(reject_user_id, "*Регистрация отклонена. Попробуйте снова.*", parse_mode='Markdown')
            del pending_users[reject_user_id]

@bot.message_handler(func=lambda m: user_states.get(m.from_user.id) == "entering_time_in")
def handle_time_in(message):
    try:
        time_in = datetime.strptime(message.text.strip(), "%H:%M").time()
        shift_data[message.from_user.id]["time_in"] = time_in.strftime("%H:%M")
        user_states[message.from_user.id] = "entering_time_out"
        bot.send_message(message.chat.id, "Время ухода (ЧЧ:ММ):")
    except ValueError:
        bot.send_message(message.chat.id, "Неверный формат. Пример: 09:00")

@bot.message_handler(func=lambda m: user_states.get(m.from_user.id) == "entering_time_out")
def handle_time_out(message):
    try:
        time_out = datetime.strptime(message.text.strip(), "%H:%M").time()
        user_id = message.from_user.id
        shift_data[user_id]["time_out"] = time_out.strftime("%H:%M")
        ti = datetime.strptime(shift_data[user_id]["time_in"], "%H:%M")
        to = datetime.strptime(shift_data[user_id]["time_out"], "%H:%M")
        if to < ti:
            to += timedelta(days=1)
        total_hours = round((to - ti).total_seconds() / 3600, 2)
        shift_data[user_id]["total_hours"] = total_hours
        data = shift_data[user_id]
        bot.send_message(
            user_id,
            f"Проверьте данные:\n"
            f"Дата: {data['date']}\n"
            f"Заведение: {data['point']}\n"
            f"Приход: {data['time_in']}\n"
            f"Уход: {data['time_out']}\n"
            f"Часов: {total_hours}\n\n"
            f"Подтвердить?",
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("Да", callback_data="confirm_shift"),
                InlineKeyboardButton("Нет", callback_data="log_shift")
            )
        )
        user_states[user_id] = "confirming_shift"
    except ValueError:
        bot.send_message(message.chat.id, "Неверный формат. Пример: 18:00")

@bot.message_handler(func=lambda message: True)
def handle_text(message):
    user_id = message.from_user.id
    state = user_states.get(user_id)
    if state == "waiting_for_name":
        name = message.text.strip()
        username = message.from_user.username or "Не указан"
        pending_users[user_id] = name
        bot.send_message(
            user_id,
            f"*Заявка отправлена!*\nОжидайте подтверждения.",
            parse_mode='Markdown'
        )
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("Подтвердить", callback_data=f"confirm_{user_id}"),
            InlineKeyboardButton("Отклонить", callback_data=f"reject_{user_id}")
        )
        admin_msg = f"*Новая регистрация!*\n\nИмя: {escape_md_v2(name)}\nUsername: @{escape_md_v2(username)}\nID: {user_id}"
        try:
            bot.send_message(ADMIN_ID, admin_msg, parse_mode='MarkdownV2', reply_markup=markup)
        except:
            bot.send_message(ADMIN_ID, admin_msg.replace('*', '').replace('\\', ''), reply_markup=markup)
        user_states.pop(user_id, None)

# Flask и запуск
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
    else:
        flask.abort(403)

if __name__ == '__main__':
    bot.remove_webhook()
    bot.set_webhook(url='https://telegram-bot-1-ydll.onrender.com')
    scheduler = BackgroundScheduler(timezone=zoneinfo.ZoneInfo("Europe/Moscow"))
    scheduler.add_job(send_reminders, 'cron', hour=20, minute=58)
    scheduler.start()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)