# Базовый образ с Python и Node
FROM nikolaik/python-nodejs:python3.12-nodejs20-alpine

# Установка nginx и supervisor
RUN apk add --no-cache nginx supervisor

# Копируем бот (Python)
WORKDIR /app/bot
COPY *.py requirements.txt credentials.json photo_2025-10-28_01-49-34.jpg ./
RUN pip install -r requirements.txt

# Копируем Mini App
WORKDIR /app/mini-app/backend
COPY mini-app/backend/ .
RUN npm install
COPY mini-app/frontend/ /app/mini-app/frontend
RUN npm run build

# Nginx конфиг
COPY nginx.conf /etc/nginx/http.d/default.conf

# Supervisor конфиг
COPY supervisord.conf /etc/supervisord.conf

# .env не нужен — Render inject env vars
ENV PYTHONUNBUFFERED=1
ENV NODE_ENV=production

EXPOSE 80

CMD ["supervisord", "-c", "/etc/supervisord.conf"]