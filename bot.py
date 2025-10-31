import os
import logging
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
    ConversationHandler,
)

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_CHAT_ID = int(os.environ["ADMIN_CHAT_ID"])

NAME = 1

logging.basicConfig(level=logging.INFO)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[KeyboardButton("Зарегистрироваться")]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text("Привет! Нажми кнопку, чтобы зарегистрироваться:", reply_markup=reply_markup)
    return NAME

async def handle_registration_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "Зарегистрироваться":
        await update.message.reply_text("Пожалуйста, введите ваше имя:")
        return NAME
    else:
        user_full_name = update.message.text.strip()
        user = update.effective_user

        username = f"@{user.username}" if user.username else "нет юзернейма"
        user_id = user.id
        first_name = user.first_name or "не указано"

        await update.message.reply_text("Вы успешно зарегистрированы!")

        admin_message = (
            f"Новая регистрация:\n"
            f"Имя: {user_full_name}\n"
            f"Telegram: {username}\n"
            f"ID: {user_id}\n"
            f"First name: {first_name}"
        )
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_message)

        return ConversationHandler.END

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_registration_button)],
        },
        fallbacks=[],
    )

    app.add_handler(conv_handler)

    port = int(os.environ.get("PORT", 8000))
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{os.environ['RENDER_EXTERNAL_URL']}/{BOT_TOKEN}"
    )

if __name__ == "__main__":
    main()
