# cripto2

Шаблон Telegram-бота для инвестиций/стейкинга на `python-telegram-bot` + `sqlite3` + `apscheduler`.

## Запуск

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# заполните BOT_TOKEN
python -m bot.main
```

## Что реализовано
- Главное меню: Кошелек / Информация / Чат / Рефералы
- Кошелек: баланс, пополнение (демо), вывод, стейкинг, история
- Стейкинг: планы и доход с автозачислением после срока
- Реферальная ссылка и базовая статистика
- Все проценты, дни, минимумы, названия и контакты настраиваются через `.env`

## Структура
- `bot/config.py` — переменные и тарифные планы
- `bot/db.py` — БД и бизнес-операции
- `bot/main.py` — Telegram UI/handlers
