import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import flask
import os
import logging
import pandas as pd
from datetime import datetime
import requests
import io

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Токен бота и ID админа
BOT_TOKEN = '7478861606:AAF-7eV0XjTn7S_6Q_caIk7Y27kGsfU_f-A'  # Замени на свой токен
ADMIN_ID = 476747112  # Замени на свой user ID (число)

bot = telebot.TeleBot(BOT_TOKEN)

# Словарь для хранения состояний пользователей
user_states = {}

# URL для экспорта Google Sheets в формате XLSX
EXCEL_URL = 'https://docs.google.com/spreadsheets/d/1SsG4uRtpslwSeZFZsIjWOAesrHvT6WhxrNoCgYRTUfg/export?format=xlsx'


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


# Функция для генерации главного меню
def get_main_menu_markup(registered):
    markup = InlineKeyboardMarkup()
    if not registered:
        markup.add(InlineKeyboardButton("Зарегистрироваться ✅", callback_data="register"))
    markup.add(InlineKeyboardButton("Узнать зарплату 💰", callback_data="salary"))
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

    bot.send_message(
        message.chat.id,
        welcome_msg,
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
        bot.answer_callback_query(call.id)
        bot.edit_message_text(
            "*Выберите месяц для просмотра зарплаты:* 📅",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode='Markdown',
            reply_markup=get_month_menu_markup()
        )

    elif call.data.startswith("month_"):
        month = call.data.split("_")[1]
        bot.answer_callback_query(call.id)

        name, hours_first, hours_second, total_hours, first_advance, second_advance, total_salary = get_salary_data(
            month, user_id)

        if name is None:
            salary_msg = "*Данные не найдены для вашего ID в этом месяце.* 😔"
        else:
            salary_msg = f"**Ваша зарплата за {month}:** 💼\n\n" \
                         f"**Имя:** {name} 👤\n\n" \
                         f"**Отработано часов за 1 половину:** {hours_first} ⏰\n" \
                         f"**Отработано часов за 2 половину:** {hours_second} ⏰\n" \
                         f"**Всего часов:** {total_hours} ⏱️🔥\n\n" \
                         f"**Первый аванс:** {first_advance} руб. 💰\n" \
                         f"**Второй аванс:** {second_advance} руб. 💰\n" \
                         f"**Итоговая з/п:** {total_salary} руб. 💵🎉"

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

        bot.edit_message_text(
            welcome_msg,
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

        bot.edit_message_text(
            welcome_msg,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode='Markdown',
            reply_markup=markup
        )


# Обработчик текстовых сообщений (для регистрации)
@bot.message_handler(func=lambda message: True)
def handle_text(message):
    user_id = message.from_user.id
    state = user_states.get(user_id)

    if state == "waiting_for_name":
        name = message.text.strip()
        username = message.from_user.username or "Не указан"
        # Отправляем ответ пользователю
        bot.send_message(
            user_id,
            f"*Вы успешно зарегистрированы! 🎉*\n\nВаше имя: {name}\n\nТеперь используйте /start для меню.",
            parse_mode='Markdown'
        )
        # Отправляем данные админу
        try:
            bot.send_message(
                ADMIN_ID,
                f"*Новая регистрация! 📋*\n\nИмя: {name}\nUsername: @{username}\nID: {user_id}",
                parse_mode='Markdown'
            )
        except Exception as e:
            logging.error(f"Ошибка отправки админу: {e}")
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
    # Запускаем Flask сервер
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)