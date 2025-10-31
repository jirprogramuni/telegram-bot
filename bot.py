import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import flask
import os
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Токен бота и ID админа
BOT_TOKEN = '8341734422:AAFItc0lswkEitKsJwhR7x19-Od7a1n2J68'  # Замени на свой токен
ADMIN_ID = 476747112  # Замени на свой user ID (число)

bot = telebot.TeleBot(BOT_TOKEN)

# Словарь для хранения состояний пользователей (чтобы знать, когда ждать имя)
user_states = {}


# Обработчик /start
@bot.message_handler(commands=['start'])
def start(message):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Зарегистрироваться ✅", callback_data="register"))

    bot.send_message(
        message.chat.id,
        "*Добро пожаловать!*\n\nНажмите кнопку ниже, чтобы зарегистрироваться. 😊",
        parse_mode='Markdown',
        reply_markup=markup
    )


# Обработчик нажатия кнопки
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


# Обработчик текстовых сообщений (для ввода имени)
@bot.message_handler(func=lambda message: True)
def handle_text(message):
    user_id = message.from_user.id
    if user_id in user_states and user_states[user_id] == "waiting_for_name":
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
    # Замени 'https://your-app-name.onrender.com/' на URL твоего Render-приложения
    bot.set_webhook(url='https://telegram-bot-1-ydll.onrender.com')

    # Запускаем Flask сервер
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)