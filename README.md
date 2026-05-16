# cripto2

Telegram-бот инвестиционного проекта на `python-telegram-bot 21.x` + `SQLite` + `APScheduler`.

## Запуск

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# заполните BOT_TOKEN и BOT_USERNAME
python -m bot.main
```

## Что реализовано
- Главное меню с баннером (URL/локальный путь из `BANNER_PATH`) и fallback на текст.
- Экраны: Информация, Кошелек, Пополнение, Вывод, Стейкинг, Мои стейки, История, Рефералы, Поддержка.
- Реферальная система: `ref_{user_id}`, привязка при `/start <code>`, 5% бонус с успешных депозитов.
- История транзакций со статусами `pending/completed/failed` -> `⏳/✅/❌`.
- Автозавершение стейков каждые 60 секунд и зачисление суммы + прибыли.

## Важно про цветные кнопки
Telegram InlineKeyboard в Bot API (на сегодня) не поддерживает нативную заливку всей кнопки цветом. Поэтому используется максимально близкий fallback: эмодзи-индикаторы цвета (`🟢🔴🔵`) + структурная раскладка под будущие API-расширения.

## База данных
Инициализация выполняется автоматически при старте (`bot/db.py:init_db`) и создает таблицы:
- `users`
- `transactions`
- `stakes`

## Структура
- `bot/main.py` — хендлеры, FSM через `context.user_data`, маршрутизация callback.
- `bot/db.py` — SQL, транзакции, стейки, бонусы рефералов.
- `bot/config.py` — конфигурация и staking-планы.
