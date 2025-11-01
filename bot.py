import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
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


# Функция для чтения данных о зарплате
def get_salary_data(month_sheet, telegram_id):
    try:
        response = requests.get(EXCEL_URL)
        if response.status_code != 200:
            logging.error(f"Ошибка загрузки файла: {response.status_code}")
            return None, None, None, None

        file_like = io.BytesIO(response.content)
        df = pd.read_excel(file_like, sheet_name=month_sheet, engine='openpyxl')

        # Ищем строку по Telegram ID (столбец B, индекс 1)
        row = df[df.iloc[:, 1] == telegram_id]

        if row.empty:
            return None, None, None, None

        name = row.iloc[0, 0]  # Столбец A - имя
        columns = df.columns
        first_advance_col = columns.get_loc('Депозит 1') if 'Депозит 1' in columns else None
        second_advance_col = columns.get_loc('Депозит 2') if 'Депозит 2' in columns else None
        total_salary_col = columns.get_loc('Итоговая з/п') if 'Итоговая з/п' in columns else None

        first_advance = row.iloc[0, first_advance_col] if first_advance_col is not None else 0
        second_advance = row.iloc[0, second_advance_col] if second_advance_col is not None else 0
        total_salary = row.iloc[0, total_salary_col] if total_salary_col is not None else 0

        return name, first_advance, second_advance, total_salary
    except Exception as e:
        logging.error(f"Ошибка чтения данных: {e}")
        return None, None, None, None


# Обработчик /start
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    registered, name = is_registered(user_id)

    markup = InlineKeyboardMarkup()
    if not registered:
        markup.add(InlineKeyboardButton("Зарегистрироваться ✅", callback_data="register"))
    markup.add(InlineKeyboardButton("Узнать зарплату 💰", callback_data="salary"))

    if registered:
        welcome_msg = f"*Добро пожаловать, {name}!*\n\nВыберите действие ниже. 😊"
    else:
        welcome_msg = "*Добро пожаловать!*\n\nВыберите действие ниже. 😊"

    bot.send_message(
        message.chat.id,
        welcome_msg,
        parse_mode='Markdown',
        reply_markup=markup
    )


# Обработчик нажатия кнопок
@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    if call.data == "register":
        user_states[call.from_user.id] = "waiting_for_name"
        bot.answer_callback_query(call.id)
        bot.send_message(
            call.from_user.id,
            "*Введите ваше имя:* ✍️",
            parse_mode='Markdown'
        )
    elif call.data == "salary":
        # Показываем клавиатуру для выбора месяца
        markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add(KeyboardButton("Октябрь"), KeyboardButton("Ноябрь"), KeyboardButton("Декабрь"))
        # Добавь другие месяцы по необходимости
        bot.answer_callback_query(call.id)
        bot.send_message(
            call.from_user.id,
            "*Выберите месяц для просмотра зарплаты:* 📅",
            parse_mode='Markdown',
            reply_markup=markup
        )
        user_states[call.from_user.id] = "waiting_for_month"


# Обработчик текстовых сообщений
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
            f"*Вы успешно зарегистрированы! 🎉*\n\nВаше имя: {name}",
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

    elif state == "waiting_for_month":
        month = message.text.strip()
        # Поддерживаемые месяцы (названия листов)
        if month not in ["Октябрь", "Ноябрь", "Декабрь"]:  # Добавь другие
            bot.send_message(user_id, "*Неверный месяц. Попробуйте снова.* ❌")
            return

        name, first_advance, second_advance, total_salary = get_salary_data(month, user_id)

        if name is None:
            bot.send_message(user_id, "*Данные не найдены для вашего ID в этом месяце.* 😔")
        else:
            bot.send_message(
                user_id,
                f"*Ваша зарплата за {month}:* 💼\n\n"
                f"Имя: {name}\n"
                f"Первый аванс: {first_advance} руб.\n"
                f"Второй аванс: {second_advance} руб.\n"
                f"Итоговая з/п: {total_salary} руб.",
                parse_mode='Markdown'
            )
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