# Telegram comment bot

Бот отвечает на текстовые сообщения и фотографии естественным комментарием через GigaChat. В группах отвечает на упоминание, ответ боту или пересланную запись канала.

Переменные: TELEGRAM_BOT_TOKEN, GIGACHAT_CREDENTIALS, TELEGRAM_PROXY_URL. Скопируйте .env.example в .env и заполните значения. Секретные файлы .env и gigachat_key.txt не помещайте в Git.

Запуск на сервере: создайте виртуальное окружение, установите зависимости из requirements.txt и включите deploy/telegram-comment-bot.service. Проверка: systemctl is-active telegram-comment-bot.service.
