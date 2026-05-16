from datetime import UTC, datetime, timedelta
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile, Update
from telegram.error import BadRequest
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from bot import db
from bot.config import SETTINGS


def kb(rows):
    return InlineKeyboardMarkup(rows)


def main_menu_kb():
    return kb([
        [InlineKeyboardButton("💰 Кошелек", callback_data="menu_wallet"), InlineKeyboardButton("ℹ️ Информация", callback_data="menu_info")],
        [InlineKeyboardButton("💬 Чат", callback_data="menu_chat"), InlineKeyboardButton("👥 Рефералы", callback_data="menu_referrals")],
    ])


def wallet_kb():
    # Telegram не поддерживает нативную заливку inline-кнопок, эмулируем цвет эмодзи и текстом
    return kb([
        [InlineKeyboardButton("🟢 Пополнить", callback_data="wallet_deposit"), InlineKeyboardButton("🔴 Вывести", callback_data="wallet_withdraw")],
        [InlineKeyboardButton("🔵 Стейкинг", callback_data="wallet_staking"), InlineKeyboardButton("🔹 История", callback_data="wallet_history")],
        [InlineKeyboardButton("🔴 Назад", callback_data="back_main")],
    ])


def status_emoji(status):
    return {"pending": "⏳", "completed": "✅", "failed": "❌"}.get(status, "⏳")


async def show_main_menu(target, edit=False):
    caption = (
        "🏠 Главное меню\n\n"
        "Добро пожаловать в инвестиционный проект.\n"
        "Инвестируйте, используйте стейкинг и получайте доход.\n\n"
        "Выберите действие:"
    )
    async def send_text_menu():
        if edit and getattr(target, "edit_message_text", None):
            await target.edit_message_text(caption, reply_markup=main_menu_kb())
        else:
            await target.reply_text(caption, reply_markup=main_menu_kb())

    if SETTINGS.banner_path and (SETTINGS.banner_path.startswith("http") or Path(SETTINGS.banner_path).exists()):
        try:
            if edit and getattr(target, "message", None):
                await target.message.reply_photo(
                    photo=SETTINGS.banner_path if SETTINGS.banner_path.startswith("http") else InputFile(SETTINGS.banner_path),
                    caption=caption,
                    reply_markup=main_menu_kb(),
                )
            else:
                await target.reply_photo(
                    photo=SETTINGS.banner_path if SETTINGS.banner_path.startswith("http") else InputFile(SETTINGS.banner_path),
                    caption=caption,
                    reply_markup=main_menu_kb(),
                )
            return
        except (BadRequest, FileNotFoundError, OSError):
            # Если Telegram не смог обработать изображение (например, формат/битый файл),
            # показываем меню текстом, чтобы бот оставался рабочим.
            pass

    await send_text_menu()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ref_code = context.args[0] if context.args else None
    db.ensure_user(update.effective_user, ref_code)
    await show_main_menu(update.message)


async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    db.ensure_user(q.from_user)

    if q.data in {"back_main"}:
        context.user_data.clear()
        await show_main_menu(q, edit=True)
    elif q.data == "menu_info":
        txt = (
            "ℹ️ Информация о проекте\n\n"
            "Это инвестиционный проект с пополнением через Crypto Pay и Telegram Stars, "
            "выводом средств и доходом на стейкинге.\n\n"
            "📈 Доходность: от 1% до 10%\n"
            "👥 Реферальная комиссия: 5% от депозитов\n\n"
            "📅 Планы стейкинга:\n"
            "• Дневной: 1 день, +1%\n"
            "• Недельный: 7 дней, +5%\n"
            "• Месячный: 10 дней, +10%\n\n"
            "📌 Минимальные суммы:\n"
            "• Пополнение: 0.1 USDT\n"
            "• Стейкинг: 10 USDT\n"
            "• Вывод: 5 USDT\n\n"
            f"💬 Поддержка: @{SETTINGS.support_username}"
        )
        await q.edit_message_text(txt, reply_markup=kb([[InlineKeyboardButton("Назад", callback_data="back_main")]]))
    elif q.data == "menu_wallet":
        u = db.get_user(uid)
        txt = (
            "💰 Ваш кошелек\n\n"
            f"💵 Доступный баланс: {u['balance']:.2f} USDT\n"
            f"🔒 В стейкинге: {u['staked_balance']:.2f} USDT\n"
            f"📊 Активных стейков: {db.get_active_stakes_count(uid)}\n\n"
            "Выберите действие:"
        )
        await q.edit_message_text(txt, reply_markup=wallet_kb())
    elif q.data == "wallet_deposit":
        await q.edit_message_text("💼 Пополнение баланса\n\nВыберите способ пополнения:", reply_markup=kb([
            [InlineKeyboardButton("Crypto Bot", callback_data="deposit_crypto")],
            [InlineKeyboardButton("Telegram Stars", callback_data="deposit_stars")],
            [InlineKeyboardButton("Назад", callback_data="menu_wallet")],
        ]))
    elif q.data in {"deposit_crypto", "deposit_stars"}:
        method = "cryptobot" if q.data == "deposit_crypto" else "stars"
        if method == "cryptobot" and not SETTINGS.cryptobot_token:
            return await q.edit_message_text(
                "⚠️ Пополнение через Crypto Bot временно недоступно: не настроен CRYPTOBOT_TOKEN в .env",
                reply_markup=kb([[InlineKeyboardButton("Назад", callback_data="menu_wallet")]]),
            )
        context.user_data["state"] = "await_deposit"
        context.user_data["deposit_method"] = method
        await q.edit_message_text(
            f"Введите сумму пополнения (минимум {SETTINGS.min_deposit_usdt:g} USDT):",
            reply_markup=kb([[InlineKeyboardButton("Назад", callback_data="menu_wallet")]]),
        )
    elif q.data == "wallet_withdraw":
        context.user_data["state"] = "await_withdraw"
        u = db.get_user(uid)
        await q.edit_message_text(f"📤 Вывод средств\n\n💰 Ваш баланс: {u['balance']:.2f} USDT\nМинимальная сумма вывода: {SETTINGS.min_withdraw_usdt:g} USDT\n\nВведите сумму для вывода:", reply_markup=kb([[InlineKeyboardButton("Назад", callback_data="menu_wallet")]]))
    elif q.data == "wallet_staking":
        await q.edit_message_text(
            "📊 Стейкинг\n\nЗаморозьте средства на определенный период и получите гарантированную прибыль!\n\n"
            "📅 Дневной план\n• Срок: 1 день\n• Доход: +1% к депозиту\n\n"
            "📅 Недельный план\n• Срок: 7 дней\n• Доход: +5% к депозиту\n\n"
            "📈 Месячный план\n• Срок: 10 дней\n• Доход: +10% к депозиту\n\nВыберите план:",
            reply_markup=kb([
                [InlineKeyboardButton("Дневной", callback_data="staking_daily"), InlineKeyboardButton("Недельный", callback_data="staking_weekly")],
                [InlineKeyboardButton("Месячный", callback_data="staking_monthly"), InlineKeyboardButton("Мои стейки", callback_data="staking_my")],
                [InlineKeyboardButton("Назад", callback_data="menu_wallet")],
            ]),
        )
    elif q.data.startswith("staking_") and q.data in {"staking_daily", "staking_weekly", "staking_monthly"}:
        plan = q.data.split("_")[1]
        context.user_data["state"] = "await_stake"
        context.user_data["stake_plan"] = plan
        p = SETTINGS.plans[plan]
        u = db.get_user(uid)
        await q.edit_message_text(f"📊 {p.title} план стейкинга\n\n⏱ Период: {p.days} дн.\n📈 Доход: +{p.percent}%\n\n💰 Ваш баланс: {u['balance']:.2f} USDT\nМинимальная сумма: {SETTINGS.min_stake_usdt:g} USDT\n\nВведите сумму для стейкинга:", reply_markup=kb([[InlineKeyboardButton("Назад", callback_data="wallet_staking")]]))
    elif q.data == "staking_my":
        rows = db.list_active_stakes(uid)
        if not rows:
            txt = "📭 У вас пока нет активных стейков."
        else:
            parts = ["📊 Ваши активные стейки:\n"]
            for s in rows:
                parts.append(f"• {s['plan']} | {s['amount']:.2f} USDT | +{s['profit']:.2f} | до {s['end_time']} | {s['status']}")
            txt = "\n".join(parts)
        await q.edit_message_text(txt, reply_markup=kb([[InlineKeyboardButton("Назад", callback_data="wallet_staking")]]))
    elif q.data == "wallet_history":
        txs = db.list_recent_transactions(uid, 10)
        if not txs:
            txt = "📜 История пуста."
        else:
            lines = ["📜 Последние транзакции:\n"]
            for t in txs:
                lines.append(f"📤 {t['type'].title()}: {t['amount']:.2f} {t['currency']} {status_emoji(t['status'])}\n{t['created_at']}\n")
            txt = "\n".join(lines)
        await q.edit_message_text(txt, reply_markup=kb([[InlineKeyboardButton("Назад", callback_data="menu_wallet")]]))
    elif q.data == "menu_referrals":
        u = db.get_user(uid)
        with db.conn() as c:
            refs = c.execute("SELECT COUNT(*) c FROM users WHERE referrer_id=?", (uid,)).fetchone()["c"]
        link = f"https://t.me/{SETTINGS.bot_username}?start={u['referral_code']}"
        txt = f"👥 Реферальная программа\n\n🎁 Получайте 5% от депозитов ваших рефералов!\n\n📊 Ваша статистика:\n• Рефералов: {refs}\n• Заработано: {u['referral_earned']:.2f} USDT\n\n🔗 Ваша реферальная ссылка:\n{link}\n\nДелитесь ссылкой с друзьями и зарабатывайте!"
        await q.edit_message_text(txt, reply_markup=kb([[InlineKeyboardButton("Скопировать", callback_data="referrals_copy")], [InlineKeyboardButton("Назад", callback_data="back_main")]]))
    elif q.data == "referrals_copy":
        u = db.get_user(uid)
        link = f"https://t.me/{SETTINGS.bot_username}?start={u['referral_code']}"
        await q.message.reply_text(f"Скопируйте ссылку:\n{link}")
    elif q.data == "menu_chat":
        await q.edit_message_text(f"💬 Поддержка: @{SETTINGS.support_username}", reply_markup=kb([[InlineKeyboardButton("Открыть поддержку", url=f"https://t.me/{SETTINGS.support_username}")], [InlineKeyboardButton("Назад", callback_data="back_main")]]))


async def message_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")
    if not state:
        return
    uid = update.effective_user.id
    try:
        amount = float(update.message.text.replace(",", "."))
    except ValueError:
        return await update.message.reply_text("Введите корректное число.")
    if amount <= 0:
        return await update.message.reply_text("Сумма должна быть больше 0.")

    user = db.get_user(uid)
    if state == "await_deposit":
        if amount < SETTINGS.min_deposit_usdt:
            return await update.message.reply_text(f"Минимальная сумма пополнения: {SETTINGS.min_deposit_usdt:g} USDT")
        method = context.user_data.get("deposit_method")
        tx = db.add_transaction(uid, "deposit", amount, status="pending", meta={"method": method})
        db.complete_transaction(tx)
        db.update_balance(uid, delta_balance=amount)
        db.apply_referral_bonus_if_needed(uid, amount, SETTINGS.referral_percent)
        context.user_data.clear()
        return await update.message.reply_text(f"✅ Пополнение подтверждено: +{amount:.2f} USDT")

    if state == "await_withdraw":
        if amount < SETTINGS.min_withdraw_usdt:
            return await update.message.reply_text(f"Минимальная сумма вывода: {SETTINGS.min_withdraw_usdt:g} USDT")
        if amount > user["balance"]:
            return await update.message.reply_text("Недостаточно средств на балансе.")
        db.update_balance(uid, delta_balance=-amount)
        db.add_transaction(uid, "withdraw", amount, status="pending", meta={"note": "manual processing"})
        context.user_data.clear()
        return await update.message.reply_text("✅ Заявка на вывод создана и отправлена в обработку.")

    if state == "await_stake":
        if amount < SETTINGS.min_stake_usdt:
            return await update.message.reply_text(f"Минимальная сумма стейкинга: {SETTINGS.min_stake_usdt:g} USDT")
        if amount > user["balance"]:
            return await update.message.reply_text("Недостаточно средств на балансе.")
        plan = SETTINGS.plans[context.user_data["stake_plan"]]
        profit = round(amount * plan.percent / 100, 2)
        total = round(amount + profit, 2)
        end = (datetime.now(UTC) + timedelta(days=plan.days)).strftime("%Y-%m-%d %H:%M:%S")
        db.update_balance(uid, delta_balance=-amount, delta_staked=amount)
        db.create_stake(uid, plan.key, amount, plan.percent, profit, total, end)
        db.add_transaction(uid, "stake", amount, status="completed", completed=True, meta={"plan": plan.key})
        context.user_data.clear()
        return await update.message.reply_text(
            f"✅ Стейкинг активирован!\n\n📊 План: {plan.title}\n💰 Сумма: {amount:.2f} USDT\n📈 Доход: +{profit:.2f} USDT ({plan.percent}%)\n"
            f"💵 Итого к получению: {total:.2f} USDT\n⏱ Период: {plan.days} дн.\n⏰ Завершится: {end}\n\n"
            "Средства будут автоматически зачислены на баланс после окончания срока."
        )


def main():
    db.init_db()
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(db.process_finished_stakes, "interval", minutes=1)
    scheduler.start()

    app = Application.builder().token(SETTINGS.bot_token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_input))
    app.run_polling()


if __name__ == "__main__":
    main()
