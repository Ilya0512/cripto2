# cripto2

Telegram-бот инвестиционного проекта на **Aiogram 3.x** + **SQLite** + **APScheduler**.

## Запуск

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# заполните BOT_TOKEN, BOT_USERNAME, SUPPORT_USERNAME и лимиты
python -m bot.main
```

## Переменные `.env`
- `BOT_TOKEN`
- `BOT_USERNAME`
- `SUPPORT_USERNAME`
- `BANNER_PATH`
- `MIN_DEPOSIT_USDT`
- `MIN_STAKE_USDT`
- `MIN_WITHDRAW_USDT`
- `REFERRAL_PERCENT`

## Функциональность
- `/start` с баннером по локальному пути `BANNER_PATH` и fallback на текст.
- Главное меню 2x2 (Кошелек, Информация, Чат, Рефералы).
- Кошелек с цветными кнопками `ButtonStyle`.
- Пополнение/вывод/стейкинг/история/рефералы.
- Реферальная ссылка формата `https://t.me/<BOT_USERNAME>?start=<referral_code>`.
- Автозавершение стейков (cron каждые 60 секунд).
