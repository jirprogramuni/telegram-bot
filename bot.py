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

# Токен бота и ID админа
BOT_TOKEN = '7478861606:AAF-7eV0XjTn7S_6Q_caIk7Y27kGsfU_f-A'  # Замени на свой токен
ADMIN_ID = 476747112  # Замени на свой user ID (число)

bot = telebot.TeleBot(BOT_TOKEN)

# Словарь для хранения состояний пользователей
user_states = {}

# Словарь для pending регистраций
pending_users = {}  # {user_id: name}

# URL для экспорта Google Sheets в формате XLSX (для чтения)
EXCEL_URL = 'https://docs.google.com/spreadsheets/d/1SsG4uRtpslwSeZFZsIjWOAesrHvT6WhxrNoCgYRTUfg/export?format=xlsx'
TABEL_URL = 'https://docs.google.com/spreadsheets/d/1q6Rqx3ypWYZAD74MdH-iz-tN5aAANrnDglLysvHg9_8/export?format=xlsx'

# Для записи в Google Sheets (нужны credentials.json, загрузи на Render)
SCOPE = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
CREDS_FILE = 'credentials.json'  # Загрузи service account JSON
creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
client = gspread.authorize(creds)
SHEET_ID = '1SsG4uRtpslwSeZFZsIjWOAesrHvT6WhxrNoCgYRTUfg'  # ID таблицы
sheet = client.open_by_key(SHEET_ID)

# Helper to escape special chars for MarkdownV2
def escape_md_v2(text):
    special_chars = r'_*[]()~`>#+-=|{}.!'
    return ''.join(['\\' + char if char in special_chars else char for char in text])


# Функция для проверки регистрации пользователя
def is_registered(user_id):
    try:
        response = requests.get(EXCEL_URL)
        if response.status_code != 200:
            logging.error(f"Ошибка загрузки файла: {response.status_code}")
            return False, None

        file_like = io.BytesIO(response.content)
        df = pd.read_excel(file_like, sheet_name="Список сотрудников", engine='openpyxl')

        # Ищем строку по Telegram ID (столбец B, индекс 1)
        row = df[df.iloc[:, 1] == user_id]

        if row.empty:
            return False, None

        name = row.iloc[0, 0]  # Столбец A - имя
        return True, name
    except Exception as e:
        logging.error(f"Ошибка проверки регистрации: {e}")
        return False, None


# Функция для добавления в sheet (оставляем, но не используем в confirm, чтобы админ добавлял вручную)
def add_to_sheet(name, user_id):
    try:
        worksheet = sheet.worksheet("Список сотрудников")
        worksheet.append_row([name, user_id])
        return True
    except Exception as e:
        logging.error(f"Ошибка добавления в sheet: {e}")
        return False


# Функция для чтения данных о зарплате и часах
def get_salary_data(month_sheet, telegram_id):
    try:
        response = requests.get(EXCEL_URL)
        if response.status_code != 200:
            logging.error(f"Ошибка загрузки файла: {response.status_code}")
            return None, None, None, None, None, None, None

        file_like = io.BytesIO(response.content)
        df = pd.read_excel(file_like, sheet_name=month_sheet, engine='openpyxl')

        # Ищем строку по Telegram ID (столбец B, индекс 1)
        row = df[df.iloc[:, 1] == telegram_id]

        if row.empty:
            return None, None, None, None, None, None, None

        name = row.iloc[0, 0]  # Столбец A - имя
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


# Функция для получения данных о табеле
def get_tabel_data(user_name, month_sheet):
    try:
        response = requests.get(TABEL_URL)
        if response.status_code != 200:
            logging.error(f"Ошибка загрузки табеля: {response.status_code}")
            return []

        file_like = io.BytesIO(response.content)
        df = pd.read_excel(file_like, sheet_name=month_sheet, engine='openpyxl', header=None, parse_dates=False)  # Добавили parse_dates=False

        # Определяем точки: ассоциируем каждый столбец с точкой
        header = df.iloc[0]
        points = {}
        current_point = None
        for col in range(2, df.shape[1]):
            if pd.notna(header[col]):
                current_point = header[col]
            if current_point:
                points[col] = current_point

        # Словарь для родительного падежа месяцев
        month_genitive = {
            'Январь': 'января',
            'Февраль': 'февраля',
            'Март': 'марта',
            'Апрель': 'апреля',
            'Май': 'мая',
            'Июнь': 'июня',
            'Июль': 'июля',
            'Август': 'августа',
            'Сентябрь': 'сентября',
            'Октябрь': 'октября',
            'Ноябрь': 'ноября',
            'Декабрь': 'декабря'
        }

        base = datetime(1899, 12, 30)  # База для Excel дат (Windows версия)
        shifts = []
        for row_idx in range(1, df.shape[0]):  # Переименовали row в row_idx для ясности
            day_abbr = df.iloc[row_idx, 0]
            if pd.isna(day_abbr):
                continue
            serial = df.iloc[row_idx, 1]
            if pd.isna(serial):
                continue

            # Обработка serial: если datetime, конвертируем в дату напрямую
            if isinstance(serial, datetime):
                date = serial
            else:
                try:
                    serial = float(serial)  # На случай, если это float
                    date = base + timedelta(days=serial)
                except (ValueError, TypeError):
                    continue

            for col in range(2, df.shape[1]):
                cell = df.iloc[row_idx, col]
                if isinstance(cell, str) and user_name in cell:  # Проверяем наличие имени (на случай с ролью)
                    point = points.get(col)
                    if point:
                        shift_str = f"{day_abbr}, {date.day} {month_genitive.get(month_sheet, month_sheet.lower())}: {point}"
                        shifts.append(shift_str)

        return shifts
    except Exception as e:
        logging.error(f"Ошибка чтения табеля: {e}")
        return []


# Функция для отправки напоминаний
def send_reminders():
    try:
        # Загрузка списка сотрудников
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

        # Определение завтрашней даты
        now = datetime.now()
        tomorrow = now + timedelta(days=1)
        month_names = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь']
        month_sheet = month_names[tomorrow.month - 1]

        # Словарь для родительного падежа месяцев
        month_genitive = {
            'Январь': 'января',
            'Февраль': 'февраля',
            'Март': 'марта',
            'Апрель': 'апреля',
            'Май': 'мая',
            'Июнь': 'июня',
            'Июль': 'июля',
            'Август': 'августа',
            'Сентябрь': 'сентября',
            'Октябрь': 'октября',
            'Ноябрь': 'ноября',
            'Декабрь': 'декабря'
        }

        base = datetime(1899, 12, 30)
        serial_tomorrow = (tomorrow - base).days

        # Загрузка табеля
        response = requests.get(TABEL_URL)
        if response.status_code != 200:
            logging.error(f"Ошибка загрузки табеля: {response.status_code}")
            return

        file_like = io.BytesIO(response.content)
        df_tabel = pd.read_excel(file_like, sheet_name=month_sheet, engine='openpyxl', header=None, parse_dates=False)

        # Определяем точки
        header = df_tabel.iloc[0]
        points = {}
        current_point = None
        for col in range(2, df_tabel.shape[1]):
            if pd.notna(header[col]):
                current_point = header[col]
            if current_point:
                points[col] = current_point

        # Находим строку для завтрашнего дня
        shift_row = None
        for r in range(1, df_tabel.shape[0]):
            s = df_tabel.iloc[r, 1]
            if isinstance(s, (int, float)) and int(s) == serial_tomorrow:
                shift_row = r
                break

        if shift_row is None:
            logging.info("Нет смен на завтра")
            return

        # Извлекаем имена и точки
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


# Функция для генерации главного меню
def get_main_menu_markup(registered):
    markup = InlineKeyboardMarkup(row_width=2)
    if not registered:
        markup.add(InlineKeyboardButton("Зарегистрироваться ✅", callback_data="register"))
    else:
        markup.add(
            InlineKeyboardButton("Узнать зарплату 💰", callback_data="salary"),
            InlineKeyboardButton("Мой табель 📅", callback_data="tabel")
        )
        markup.add(
            InlineKeyboardButton("Заполнить форму 📝", url="https://docs.google.com/forms/u/0/d/e/1FAIpQLSdt4Xl89HwFdwWvGSzCxBh0zh-i2lQNcELEJYfspkyxmzGIsw/formResponse")
        )
    return markup


# Функция для генерации меню месяцев
def get_month_menu_markup():
    markup = InlineKeyboardMarkup(row_width=3)
    markup.add(
        InlineKeyboardButton("Октябрь", callback_data="month_Октябрь"),
        InlineKeyboardButton("Ноябрь", callback_data="month_Ноябрь"),
        InlineKeyboardButton("Декабрь", callback_data="month_Декабрь")
    )
    markup.add(InlineKeyboardButton("Назад 🔙", callback_data="back_to_menu"))
    return markup


# Обработчик /start
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    registered, name = is_registered(user_id)

    if registered:
        welcome_msg = f"*Добро пожаловать, {name}!*\n\nВыберите действие ниже. 😊"
    else:
        welcome_msg = "*Добро пожаловать!*\n\nВыберите действие ниже. 😊"

    markup = get_main_menu_markup(registered)

    bot.send_photo(
        message.chat.id,
        photo=open("photo_2025-10-28_01-49-34.jpg", "rb"),
        caption=welcome_msg,
        parse_mode='Markdown',
        reply_markup=markup
    )


# Обработчик нажатия кнопок
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
        bot.send_message(
            user_id,
            "*Введите ваше имя:* ✍️",
            parse_mode='Markdown'
        )

    elif call.data == "salary":
        if not registered:
            bot.answer_callback_query(call.id, "Вы не зарегистрированы! Сначала зарегистрируйтесь.")
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
            bot.answer_callback_query(call.id, "Вы не зарегистрированы! Сначала зарегистрируйтесь.")
            return
        bot.answer_callback_query(call.id)

        # Определяем текущий месяц
        month_names = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь']
        current_month = month_names[datetime.now().month - 1]

        shifts = get_tabel_data(name, current_month)

        if not shifts:
            tabel_msg = f"*Нет смен в {current_month.lower()}.* 😔"
        else:
            tabel_msg = f"**Ваши смены за {current_month}:** 📅\n\n" + "\n".join([f"- {shift}" for shift in shifts])

        bot.send_message(
            call.message.chat.id,
            tabel_msg,
            parse_mode='Markdown'
        )

        # Reset the menu message back to main
        if registered:
            welcome_msg = f"*Добро пожаловать, {name}!*\n\nВыберите действие ниже. 😊"
        else:
            welcome_msg = "*Добро пожаловать!*\n\nВыберите действие ниже. 😊"

        markup = get_main_menu_markup(registered)

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

        name, hours_first, hours_second, total_hours, first_advance, second_advance, total_salary = get_salary_data(
            month, user_id)

        if name is None:
            salary_msg = "*Данные не найдены для вашего ID в этом месяце.* 😔"
        else:
            salary_msg = f"*Ваша зарплата за {month}:* 💼\n\n" \
                         f"*Имя:* {name} 👤\n\n" \
                         f"*Отработано часов за 1 половину:* {hours_first} ⏰\n" \
                         f"*Отработано часов за 2 половину:* {hours_second} ⏰\n" \
                         f"*Всего часов:* {total_hours} ⏱️🔥\n\n" \
                         f"*Первый аванс:* {first_advance} руб. 💰\n" \
                         f"*Второй аванс:* {second_advance} руб. 💰\n" \
                         f"*Итоговая з/п:* {total_salary} руб. 💵🎉"

        bot.send_message(
            call.message.chat.id,
            salary_msg,
            parse_mode='Markdown'
        )

        # Reset the menu message back to main
        if registered:
            welcome_msg = f"*Добро пожаловать, {name}!*\n\nВыберите действие ниже. 😊"
        else:
            welcome_msg = "*Добро пожаловать!*\n\nВыберите действие ниже. 😊"

        markup = get_main_menu_markup(registered)

        bot.edit_message_caption(
            caption=welcome_msg,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode='Markdown',
            reply_markup=markup
        )

    elif call.data == "back_to_menu":
        bot.answer_callback_query(call.id)
        if registered:
            welcome_msg = f"*Добро пожаловать, {name}!*\n\nВыберите действие ниже. 😊"
        else:
            welcome_msg = "*Добро пожаловать!*\n\nВыберите действие ниже. 😊"

        markup = get_main_menu_markup(registered)

        bot.edit_message_caption(
            caption=welcome_msg,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode='Markdown',
            reply_markup=markup
        )

    elif call.data.startswith("confirm_"):
        if user_id != ADMIN_ID:
            bot.answer_callback_query(call.id, "Только админ может подтверждать!")
            return
        confirm_user_id = int(call.data.split("_")[1])
        confirm_name = pending_users.get(confirm_user_id)
        if confirm_name:
            # Предполагаем, что админ уже добавил в Sheets вручную — не добавляем автоматически
            bot.answer_callback_query(call.id, "Подтверждено!")
            bot.edit_message_reply_markup(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=None  # Удаляем кнопки
            )

            # Проверяем регистрацию (должна быть True, если админ добавил)
            registered, name = is_registered(confirm_user_id)
            if registered:
                welcome_msg = f"*Добро пожаловать, {name}!*\n\nВыберите действие ниже. 😊"
                markup = get_main_menu_markup(registered=True)  # Меню с "Узнать зарплату"

                bot.send_message(
                    confirm_user_id,
                    "*Ваша регистрация подтверждена! 🎉*",
                    parse_mode='Markdown'
                )
                bot.send_photo(
                    confirm_user_id,
                    photo=open("photo_2025-10-28_01-49-34.jpg", "rb"),
                    caption=welcome_msg,
                    parse_mode='Markdown',
                    reply_markup=markup
                )
            else:
                # Если админ забыл добавить в Sheets
                bot.send_message(
                    confirm_user_id,
                    "*Регистрация подтверждена, но данные не найдены. Свяжитесь с админом.* 😔",
                    parse_mode='Markdown'
                )
                bot.answer_callback_query(call.id, "Пользователь не в Sheets — добавьте вручную!")

            del pending_users[confirm_user_id]
        else:
            bot.answer_callback_query(call.id, "Пользователь не найден!")

    elif call.data.startswith("reject_"):
        if user_id != ADMIN_ID:
            bot.answer_callback_query(call.id, "Только админ может отклонять!")
            return
        reject_user_id = int(call.data.split("_")[1])
        if reject_user_id in pending_users:
            bot.answer_callback_query(call.id, "Отклонено!")
            bot.edit_message_reply_markup(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=None  # Удаляем кнопки
            )
            bot.send_message(
                reject_user_id,
                "*Ваша регистрация отклонена админом. 😔*\n\nПопробуйте снова или свяжитесь с поддержкой.",
                parse_mode='Markdown'
            )
            del pending_users[reject_user_id]
        else:
            bot.answer_callback_query(call.id, "Пользователь не найден!")


# Обработчик текстовых сообщений (для регистрации)
@bot.message_handler(func=lambda message: True)
def handle_text(message):
    user_id = message.from_user.id
    state = user_states.get(user_id)

    if state == "waiting_for_name":
        name = message.text.strip()
        username = message.from_user.username or "Не указан"
        # Сохраняем pending
        pending_users[user_id] = name
        # Отправляем пользователю
        bot.send_message(
            user_id,
            f"*Заявка на регистрацию отправлена\\!* 🎉\n\nВаше имя: {escape_md_v2(name)}\nОжидайте подтверждения от админа\\.",
            parse_mode='MarkdownV2'
        )
        # Отправляем админу с кнопками
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("Подтвердить ✅", callback_data=f"confirm_{user_id}"),
            InlineKeyboardButton("Отклонить ❌", callback_data=f"reject_{user_id}")
        )
        admin_msg = f"*Новая регистрация\\!* 📋\n\nИмя: {escape_md_v2(name)}\nUsername: @{escape_md_v2(username)}\nID: {user_id}"
        try:
            # Используем send_message с reply_markup
            bot.send_message(
                ADMIN_ID,
                admin_msg,
                parse_mode='MarkdownV2',
                reply_markup=markup  # <-- Убедись, что reply_markup передан правильно
            )
        except telebot.apihelper.ApiTelegramException as e:
            logging.error(f"Telegram API error sending to admin: {e} (user_id={user_id}, name={name})")
            # Fallback: send without parse_mode if Markdown fails (rare now with escaping)
            bot.send_message(
                ADMIN_ID,
                admin_msg.replace('*', '').replace('\\', ''),  # Strip formatting as fallback
                reply_markup=markup
            )
        except Exception as e:
            logging.error(f"Unexpected error sending to admin: {e} (user_id={user_id}, name={name})")
        # Сбрасываем состояние
        del user_states[user_id]


# Для webhook на Render
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
    # Удаляем старый webhook, если есть
    bot.remove_webhook()
    # Устанавливаем новый webhook (для Render)
    bot.set_webhook(url='https://telegram-bot-1-ydll.onrender.com')  # Замени на свой URL Render

    # Запускаем scheduler для напоминаний
    scheduler = BackgroundScheduler(timezone="Europe/Moscow")  # Укажите нужный timezone
    scheduler.add_job(send_reminders, 'cron', hour=20, minute=26)
    scheduler.start()

    # Запускаем Flask сервер
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)