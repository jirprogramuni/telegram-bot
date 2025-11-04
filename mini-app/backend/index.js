const express = require('express');
const bodyParser = require('body-parser');
const { google } = require('googleapis');
const { validateInitData } = require('@telegram-apps/init-data-node');
const TelegramBot = require('node-telegram-bot-api');
const path = require('path');
require('dotenv').config();

const app = express();
const port = process.env.MINI_APP_PORT || 3000;

app.use(bodyParser.json());
app.use(express.static(path.join(__dirname, 'public'))); // Serve frontend dist

const bot = new TelegramBot(process.env.BOT_TOKEN);
const ADMIN_ID = parseInt(process.env.ADMIN_TELEGRAM_ID);
const SHEET_ID = process.env.SHEET_ID;
const GOOGLE_KEY = JSON.parse(process.env.GOOGLE_SERVICE_ACCOUNT_KEY);

const auth = new google.auth.GoogleAuth({
  credentials: GOOGLE_KEY,
  scopes: ['https://www.googleapis.com/auth/spreadsheets'],
});
const sheets = google.sheets({ version: 'v4', auth });
const SHEET_NAME = 'Сырые ответы формы ТГ';

// Middleware to validate Telegram initData
const validateTelegram = (req, res, next) => {
  const initData = req.headers['x-telegram-init-data'];
  if (!initData) return res.status(401).json({ error: 'Missing initData' });
  try {
    validateInitData(initData, process.env.BOT_TOKEN);
    req.user = JSON.parse(new URLSearchParams(initData).get('user'));
    next();
  } catch (err) {
    res.status(401).json({ error: 'Invalid initData' });
  }
};

// POST /api/submit - Submit new shift
app.post('/api/submit', validateTelegram, async (req, res) => {
  const { date, place, startTime, endTime } = req.body;
  const user = req.user;
  const username = user.username || '';

  // Format date as DD.MM.YYYY
  const formattedDate = new Date(date).toLocaleDateString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric'
  });

  try {
    // Append to Google Sheet
    await sheets.spreadsheets.values.append({
      spreadsheetId: SHEET_ID,
      range: `${SHEET_NAME}!A:F`,
      valueInputOption: 'RAW',
      resource: {
        values: [[username, user.id, formattedDate, place, startTime, endTime]],
      },
    });

    // Notify user
    await bot.sendMessage(user.id, '✅ Ваша смена успешно зачтена!');

    // Notify admin
    const adminMsg = `[АДМИН] Новая смена:\n👤 ID: ${user.id} | @${username}\n📅 Дата: ${formattedDate}\n📍 Заведение: ${place}\n⏰ Смена: ${startTime} – ${endTime}`;
    await bot.sendMessage(ADMIN_ID, adminMsg);

    res.json({ success: true });
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: 'Server error' });
  }
});

// GET /api/admin/list - List all shifts (admin only)
app.get('/api/admin/list', validateTelegram, async (req, res) => {
  const user = req.user;
  if (user.id !== ADMIN_ID) return res.status(403).json({ error: 'Access denied' });

  try {
    const response = await sheets.spreadsheets.values.get({
      spreadsheetId: SHEET_ID,
      range: `${SHEET_NAME}!A:F`,
    });
    const rows = response.data.values || [];
    const headers = rows[0] || [];
    const data = rows.slice(1).map((row, index) => ({
      rowIndex: index + 2, // 1-based, skip header
      username: row[0],
      id: row[1],
      date: row[2],
      place: row[3],
      start: row[4],
      end: row[5],
    }));
    res.json(data);
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: 'Server error' });
  }
});

// PUT /api/admin/update - Update shift (admin only)
app.put('/api/admin/update', validateTelegram, async (req, res) => {
  const user = req.user;
  if (user.id !== ADMIN_ID) return res.status(403).json({ error: 'Access denied' });

  const { rowIndex, date, place, startTime, endTime } = req.body;

  // Format date
  const formattedDate = new Date(date).toLocaleDateString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric'
  });

  try {
    // Update specific row (columns C:F for date, place, start, end)
    await sheets.spreadsheets.values.update({
      spreadsheetId: SHEET_ID,
      range: `${SHEET_NAME}!C${rowIndex}:F${rowIndex}`,
      valueInputOption: 'RAW',
      resource: {
        values: [[formattedDate, place, startTime, endTime]],
      },
    });
    res.json({ success: true });
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: 'Server error' });
  }
});

// Serve frontend
app.get('*', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

app.listen(port, () => {
  console.log(`Mini App server running on port ${port}`);
});