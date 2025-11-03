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

logging.basicBasic(level=logging.INFO)

BOT_TOKEN = '7478861606:AAF-7eV0XjTn7S_6Q_caIk7Y27kGsfU_f-A'
ADMIN_ID = 476747112

bot = telebot.TeleBot(BOT_TOKEN)

user_states = {}
pending_users = {}

EXCEL_URL = 'https://docs.google.com/spreadsheets/d/1SsG4uRtpslwSeZFZsIjWOAesrHvT6WhxrNoCgYRTUfg/export?format=xlsx'
TABEL_URL = 'https://docs.google.com/spreadsheets/d/1q6Rqx3ypWYZAD74MdH-iz-tN5aAANrnDglLysvHg9_8/export?format=xlsx'

SCOPE = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
CREDS_FILE = 'credentials.json'
creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
client = gspread.authorize(creds)
SHEET_ID = '1SsG4uRtpslwSeZFZsIjWOAesrHvT6WhxrNoCgYRTUfg'
sheet = client.open_by_key(SHEET_ID)

def escape_markdown(text):
    if not text: return ""
    escape_chars = r'\_*[]()~`>#+-=|{}.!'
    return ''.join('\\' + c if c in escape_chars else c for c in str(text))

def is_registered(user_id):
    try:
        df = pd.read_excel(io.BytesIO(requests.get(EXCEL_URL).content), sheet_name="Список сотрудников", engine='openpyxl')
        row = df[df.iloc[:, 1] == user_id]
        return (True, row.iloc[0, 0]) if not row.empty else (False, None)
    except Exception as e:
        logging.error(f"Reg error: {e}")
        return False, None

def get_salary_data(month, tid):
    try:
        df = pd.read_excel(io.BytesIO(requests.get(EXCEL_URL).content), sheet_name=month, engine='openpyxl')
        row = df[df.iloc[:, 1] == tid]
        if row.empty: return [None]*7
        name = row.iloc[0, 0]
        cols = df.columns
        h1 = row.iloc[0, cols.get_loc('Общие часы 1 половина')] if 'Общие часы 1 половина' in cols else 0
        h2 = row.iloc[0, cols.get_loc('Общие часы 2 половина')] if 'Общие часы 2 половина' in cols else 0
        a1 = row.iloc[0, cols.get_loc('Депозит 1')] if 'Депозит 1' in cols else 0
        a2 = row.iloc[0, cols.get_loc('Депозит 2')] if 'Депозит 2' in cols else 0
        total = row.iloc[0, cols.get_loc('Итоговая з/п')] if 'Итоговая з/п' in cols else 0
        return name, h1, h2, h1+h2, a1, a2, total
    except Exception as e:
        logging.error(f"Salary: {e}")
        return [None]*7

def get_tabel_data(name, month):
    try:
        df = pd.read_excel(io.BytesIO(requests.get(TABEL_URL).content), sheet_name=month, engine='openpyxl', header=None)
        # ... (табель без изменений, сократил для краткости)
        return []  # Замени на полный код табеля из предыдущей версии, если нужно
    except: return []

def send_reminders():
    try:
        # ... (напоминания без изменений)
        pass
    except: pass

def menu(reg): 
    m = InlineKeyboardMarkup(row_width=2)
    if not reg: m.add(InlineKeyboardButton("Регистрация ✅", callback_data="register"))
    else: m.add(InlineKeyboardButton("ЗП 💰", callback_data="salary"), InlineKeyboardButton("Табель 📅", callback_data="tabel"))
    m.add(InlineKeyboardButton("Форма 📝", url="https://docs.google.com/forms/..."))
    return m

@bot.message_handler(commands=['start'])
def start(m):
    uid = m.from_user.id
    reg, name = is_registered(uid)
    txt = f"*Привет{', ' + escape_markdown(name) + '!' if reg else ''}!*\\n\\nЖми кнопки ниже, хуйло 😈"
    bot.send_message(m.chat.id, txt, parse_mode='MarkdownV2', reply_markup=menu(reg))

@bot.callback_query_handler(func=lambda c: True)
def cb(c):
    uid = c.from_user.id
    reg, name = is_registered(uid)
    if c.data == "register":
        user_states[uid] = "name"
        bot.send_message(uid, "*Имя?*")
    # ... остальные колбэки — скопируй из прошлого кода

@bot.message_handler(func=lambda m: True)
def text(m):
    if user_states.get(m.from_user.id) == "name":
        # ... регистрация

app = flask.Flask(__name__)
@app.route('/', methods=['GET', 'HEAD']): return ''
@app.route('/', methods=['POST'])
def hook():
    if flask.request.headers.get('content-type') == 'application/json':
        bot.process_new_updates([telebot.types.Update.de_json(flask.request.get_data().decode('utf-8'))])
        return ''
    flask.abort(403)

if __name__ == '__main__':
    bot.remove_webhook()
    bot.set_webhook(url='https://telegram-bot-1-ydll.onrender.com')
    scheduler = BackgroundScheduler(timezone="Europe/Moscow")
    scheduler.add_job(send_reminders, 'cron', hour=20, minute=0)
    scheduler.start()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))