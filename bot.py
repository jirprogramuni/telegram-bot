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

# === НАСТРОЙКИ ===
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = '7478861606:AAF-7eV0XjTn7S_6Q_caIk7Y27kGsfU_f-A'
ADMIN_ID = 476747112
bot = telebot.TeleBot(BOT_TOKEN)

user_states = {}
pending_users = {}
shift_data = {}

WORK_POINTS = [
    "КУЧИНО",
    "РЕУТОВ (Победы)",
    "ЛЕНИНА",
    "НЯМС",
    "РЕУТОВ (Юбилейный)"
]

EXCEL_URL = 'https://docs.google.com/spreadsheets/d/1SsG4uRtpslwSeZFZsIjWOAesrHvT6WhxrNoCgYRTUfg/export?format=xlsx'
TABEL_URL = 'https://docs.google.com/spreadsheets/d/1q6Rqx3ypWYZAD74MdH-iz-tN5aAANrnDglLysvHg9_8/export?format=xlsx'

SCOPE = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
CREDS_FILE = 'credentials.json'
creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
client = gspread.authorize(creds)
SHEET_ID = '1SsG4uRtpslwSeZFZsIjWOAesrHvT6WhxrNoCgYRTUfg'
sheet = client.open_by_key(SHEET_ID)

# === ПОМОЩНИКИ ===
def escape_md_v2(text):
    if not text: return ""
    special = r'_*[]()~`>#+-=|{}.!'
    return ''.join(['\\' + c if c in special else c for c in str(text)])

def shift_exists(telegram_id, date_str):
    try:
        ws = client.open_by_key(SHEET_ID).worksheet("Сырые ответы формы ТГ")
        records = ws.get_all_records()
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        formatted = date_obj.strftime("%d.%m.%Y")
        for r in records:
            if str(r.get('Telegram ID', '')) == str(telegram_id) and r.get('Дата смены', '') == formatted:
                return True
        return False
    except Exception as e:
        logging.error(f"shift_exists: {e}")
        return False

def has_edit_permission(telegram_id, date_str):
    try:
        ws = client.open_by_key(SHEET_ID).worksheet("Разрешения")
        records = ws.get_all_records()
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        formatted = date_obj.strftime("%d.%m.%Y")
        for r in records:
            if str(r.get('Telegram ID', '')) == str(telegram_id) and r.get('Дата смены', '') == formatted and r.get('Статус', '') == "активно":
                return True
        return False
    except Exception as e:
        logging.error(f"has_edit_permission: {e}")
        return False

def grant_edit_permission(telegram_id, date_str):
    try:
        ws = client.open_by_key(SHEET_ID).worksheet("Разрешения")
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        formatted = date_obj.strftime("%d.%m.%Y")
        ws.append_row([telegram_id, formatted, "активно"])
        return True
    except Exception as e:
        logging.error(f"grant_edit_permission: {e}")
        return False

def save_shift_to_sheet(telegram_id, username, date_str, point, time_in, time_out, total_hours, status="Зафиксировано"):
    try:
        ws = client.open_by_key(SHEET_ID).worksheet("Сырые ответы формы ТГ")
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        formatted = date_obj.strftime("%d.%m.%Y")
        safe_user = f"@{username}" if username else ""
        ws.append_row([safe_user, telegram_id, formatted, point, time_in, time_out, total_hours, status])
        return True
    except Exception as e:
        logging.error(f"save_shift_to_sheet: {e}")
        return False

# === КАЛЕНДАРЬ ===
def generate_calendar(year, month):
    markup = InlineKeyboardMarkup()
    month_name = calendar.month_name[month].capitalize()
    markup.add(InlineKeyboardButton(f"{month_name} {year}", callback_data="ignore"))
    markup.row(*[InlineKeyboardButton(d, callback_data="ignore") for d in ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]])
    cal = calendar.monthcalendar(year, month)
    for week in cal:
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(" ", callback_data="ignore"))
            else:
                row.append(InlineKeyboardButton(str(day), callback_data=f"date_{year}-{month:02d}-{day:02d}"))
        markup.row(*row)
    prev_m = month - 1 if month > 1 else 12
    prev_y = year if month > 1 else year - 1
    next_m = month + 1 if month < 12 else 1
    next_y = year if month < 12 else year + 1
    markup.row(
        InlineKeyboardButton("◀️", callback_data=f"cal_{prev_y}_{prev_m}"),
        InlineKeyboardButton("Назад", callback_data="back_to_menu"),
        InlineKeyboardButton("▶️", callback_data=f"cal_{next_y}_{next_m}")
    )
    return markup

# === РЕГИСТРАЦИЯ И ЗАРПЛАТА ===
def is_registered(user_id):
    try:
        r = requests.get(EXCEL_URL)
        if r.status_code != 200: return False, None
        df = pd.read_excel(io.BytesIO(r.content), sheet_name="Список сотрудников", engine='openpyxl')
        row = df[df.iloc[:, 1] == user_id]
        if row.empty: return False, None
        return True, row.iloc[0, 0]
    except: return False, None

def get_main_menu_markup(registered):
    from telebot.types import WebAppInfo
    markup = InlineKeyboardMarkup(row_width=2)
    if not registered:
        markup.add(InlineKeyboardButton("Зарегистрироваться", callback_data="register"))
    else:
        markup.add(
            InlineKeyboardButton("Зарплата", callback_data="salary"),
            InlineKeyboardButton("Табель", callback_data="tabel")
        )
        markup.add(InlineKeyboardButton("Записать смену", callback_data="log_shift"))
        markup.add(InlineKeyboardButton("Календарь смен (Мини-апп)", web_app=WebAppInfo(url="https://mini-app-wchu.onrender.com")))
        markup.add(InlineKeyboardButton("Форма", url="https://docs.google.com/forms/u/0/d/e/1FAIpQLSdt4Xl89HwFdwWvGSzCxBh0zh-i2lQNcELEJYfspkyxmzGIsw/formResponse"))
    return markup

# === ОБРАБОТЧИКИ ===
@bot.message_handler(commands=['start'])
def start(m):
    registered, name = is_registered(m.from_user.id)
    msg = f"*Добро пожаловать, {name}!*" if registered else "*Добро пожаловать!*"
    bot.send_photo(m.chat.id, open("photo_2025-10-28_01-49-34.jpg", "rb"), caption=msg, parse_mode='Markdown', reply_markup=get_main_menu_markup(registered))

@bot.callback_query_handler(func=lambda c: True)
def callback(c):
    user_id = c.from_user.id
    registered, name = is_registered(user_id)

    if c.data == "register":
        if registered: return bot.answer_callback_query(c.id, "Уже зарегистрированы!")
        user_states[user_id] = "waiting_for_name"
        bot.send_message(user_id, "*Введите имя:*", parse_mode='Markdown')
        return

    if not registered:
        bot.answer_callback_query(c.id, "Сначала зарегистрируйтесь!")
        return

    if c.data == "log_shift":
        now = datetime.now(zoneinfo.ZoneInfo("Europe/Moscow"))
        bot.edit_message_caption(chat_id=c.message.chat.id, message_id=c.message.message_id,
                                 caption="*Выберите дату:*", parse_mode='Markdown', reply_markup=generate_calendar(now.year, now.month))
        user_states[user_id] = "selecting_date"

    elif c.data.startswith("date_"):
        date_str = c.data.split("_", 1)[1]
        if shift_exists(user_id, date_str) and not has_edit_permission(user_id, date_str):
            markup = InlineKeyboardMarkup().add(InlineKeyboardButton("Запросить изменение", callback_data=f"request_edit_{date_str}"), InlineKeyboardButton("Назад", callback_data="log_shift"))
            bot.edit_message_caption(chat_id=c.message.chat.id, message_id=c.message.message_id,
                                     caption=f"Смена на {date_str} зафиксирована. Запросить изменение?", reply_markup=markup)
        else:
            shift_data[user_id] = {"date": date_str}
            user_states[user_id] = "selecting_point"
            markup = InlineKeyboardMarkup(row_width=1)
            for p in WORK_POINTS: markup.add(InlineKeyboardButton(p, callback_data=f"point_{p}"))
            markup.add(InlineKeyboardButton("Назад", callback_data="log_shift"))
            bot.edit_message_caption(chat_id=c.message.chat.id, message_id=c.message.message_id,
                                     caption=f"*Дата:* {date_str}\n*Заведение:*", parse_mode='Markdown', reply_markup=markup)

    elif c.data.startswith("point_"):
        point = c.data.split("_", 1)[1]
        shift_data[user_id]["point"] = point
        user_states[user_id] = "entering_time_in"
        bot.send_message(user_id, "Время прихода (ЧЧ:ММ):")

    elif c.data == "confirm_shift":
        data = shift_data.get(user_id)
        if not data: return
        status = "Смена не защищена" if has_edit_permission(user_id, data["date"]) else "Зафиксировано"
        success = save_shift_to_sheet(user_id, c.from_user.username, data["date"], data["point"], data["time_in"], data["time_out"], data["total_hours"], status)
        bot.send_message(user_id, "Смена сохранена!" if success else "Ошибка!")
        shift_data.pop(user_id, None); user_states.pop(user_id, None)
        bot.edit_message_caption(chat_id=c.message.chat.id, message_id=c.message.message_id,
                                 caption=f"*Добро пожаловать, {name}!*", parse_mode='Markdown', reply_markup=get_main_menu_markup(True))

    # ... (остальные callback'и без изменений — зарплата, табель и т.д.)

@bot.message_handler(func=lambda m: user_states.get(m.from_user.id) == "entering_time_in")
def time_in(m):
    try:
        t = datetime.strptime(m.text.strip(), "%H:%M").strftime("%H:%M")
        shift_data[m.from_user.id]["time_in"] = t
        user_states[m.from_user.id] = "entering_time_out"
        bot.send_message(m.chat.id, "Время ухода (ЧЧ:ММ):")
    except: bot.send_message(m.chat.id, "Формат: 09:00")

@bot.message_handler(func=lambda m: user_states.get(m.from_user.id) == "entering_time_out")
def time_out(m):
    try:
        ti = datetime.strptime(shift_data[m.from_user.id]["time_in"], "%H:%M")
        to = datetime.strptime(m.text.strip(), "%H:%M")
        if to < ti: to += timedelta(days=1)
        hours = round((to - ti).total_seconds() / 3600, 2)
        shift_data[m.from_user.id]["time_out"] = to.strftime("%H:%M")
        shift_data[m.from_user.id]["total_hours"] = hours
        data = shift_data[m.from_user.id]
        bot.send_message(m.chat.id, f"Проверьте:\nДата: {data['date']}\nЗаведение: {data['point']}\nПриход: {data['time_in']}\nУход: {data['time_out']}\nЧасов: {hours}\n\nПодтвердить?",
                         reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("Да", callback_data="confirm_shift"), InlineKeyboardButton("Нет", callback_data="log_shift")))
        user_states[m.from_user.id] = "confirming_shift"
    except: bot.send_message(m.chat.id, "Формат: 18:00")

# === FLASK ===
app = flask.Flask(__name__)

@app.route('/', methods=['GET', 'HEAD'])
def index(): return ''

@app.route('/', methods=['POST'])
def webhook():
    if flask.request.headers.get('content-type') == 'application/json':
        update = telebot.types.Update.de_json(flask.request.get_data().decode('utf-8'))
        bot.process_new_updates([update])
        return ''
    flask.abort(403)

# === НОВЫЕ МАРШРУТЫ ДЛЯ MINI APP ===
@app.route('/get-shifts', methods=['GET'])
def get_shifts():
    user_id = flask.request.args.get('user_id')
    month = flask.request.args.get('month')  # YYYY-MM
    if not user_id or not month: return flask.jsonify({"error": "bad params"}), 400
    try:
        ws = client.open_by_key(SHEET_ID).worksheet("Сырые ответы формы ТГ")
        records = ws.get_all_records()
        shifts = {}
        for r in records:
            tid = str(r.get('Telegram ID', '')).strip()
            date_raw = r.get('Дата смены', '').strip()
            if tid != user_id or not date_raw: continue
            try:
                d = datetime.strptime(date_raw, "%d.%m.%Y").strftime("%Y-%m-%d")
            except: continue
            if not d.startswith(month): continue
            shifts[d] = {
                "point": r.get('Заведение', ''),
                "time_in": r.get('Время прихода', ''),
                "time_out": r.get('Время ухода', ''),
                "total_hours": str(r.get('Всего часов', ''))
            }
        return flask.jsonify({"shifts": shifts})
    except Exception as e:
        logging.error(f"get-shifts: {e}")
        return flask.jsonify({"shifts": {}}), 500

@app.route('/save-shift', methods=['POST'])
def save_shift():
    data = flask.request.get_json(silent=True)
    if not data: return flask.jsonify({"success": False, "error": "no data"}), 400
    tid = str(data.get('telegram_id'))
    date = data.get('date')
    point = data.get('point')
    tin = data.get('time_in')
    tout = data.get('time_out')
    hours = data.get('total_hours')
    if not all([tid, date, point, tin, tout]): return flask.jsonify({"success": False, "error": "missing"}), 400
    try:
        exists = shift_exists(tid, date)
        can_edit = not exists or has_edit_permission(tid, date)
        if exists and not can_edit: return flask.jsonify({"success": False, "error": "locked"}), 403
        status = "Смена не защищена" if exists and can_edit else "Зафиксировано"
        success = save_shift_to_sheet(tid, None, date, point, tin, tout, hours, status)
        if success and exists: grant_edit_permission(tid, date)
        return flask.jsonify({"success": success})
    except Exception as e:
        logging.error(f"save-shift: {e}")
        return flask.jsonify({"success": False, "error": "server"}), 500

# === ЗАПУСК ===
if __name__ == '__main__':
    bot.remove_webhook()
    bot.set_webhook(url='https://telegram-bot-1-ydll.onrender.com')
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)