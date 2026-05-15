from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot import db
from bot.config import SETTINGS


def btn(text: str, action: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, callback_data=action)


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn("💼 Кошелек", "menu_wallet"), btn("ℹ️ Информация", "menu_info")],
        [btn("💬 Чат", "menu_chat"), btn("👥 Рефералы", "menu_refs")],
    ])


def back_button(target: str = "menu_main") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[btn("🔴 Назад", target)]])


def wallet_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn("🟢 Пополнить", "wallet_deposit"), btn("🔴 Вывести", "wallet_withdraw")],
        [btn("🔵 Стейкинг", "wallet_stake"), btn("📜 История", "wallet_history")],
        [btn("🔴 Назад", "menu_main")],
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    referrer_id = None
    if context.args and context.args[0].startswith("ref"):
        referrer_id = int(context.args[0].replace("ref", ""))
    db.ensure_user(user.id, referrer_id)
    text = (
        "Добро пожаловать! Это инвестиционный проект, где вы можете вкладывать "
        "средства в стейкинг и получать доход."
    )
    await update.message.reply_text(text, reply_markup=main_menu())


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    db.ensure_user(uid)

    if q.data == "menu_main":
        context.user_data.clear()
        await q.edit_message_text(
            "Добро пожаловать! Выберите раздел.",
            reply_markup=main_menu(),
        )
        return

    if q.data == "menu_info":
        plans = "\n".join([f"• {p.title}: {p.days} дн., +{p.percent}%" for p in SETTINGS.plans.values()])
        txt = (
            "Мы инвестиционный проект, вкладываемся в стейкинг и криптовалюту.\n"
            "Заработок на стейкинге: от 1% до 10%.\n"
            f"Реферальная комиссия: {SETTINGS.referral_percent}% от депозитов рефералов.\n\n"
            f"Минимальный депозит: {SETTINGS.min_deposit_usdt} USDT\n"
            f"Минимальный стейкинг: {SETTINGS.min_stake_usdt} USDT\n"
            f"Минимальный вывод: {SETTINGS.min_withdraw_usdt} USDT\n\n"
            f"Планы:\n{plans}"
        )
        await q.edit_message_text(txt, reply_markup=back_button())
        return

    if q.data == "menu_chat":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Открыть чат поддержки", url=SETTINGS.support_chat_url)],
            [btn("🔴 Назад", "menu_main")],
        ])
        await q.edit_message_text("Свяжитесь с поддержкой в чате:", reply_markup=kb)
        return

    if q.data == "menu_wallet":
        u = db.get_user(uid)
        active = db.get_active_stakes_count(uid)
        await q.edit_message_text(
            f"💼 Кошелек\n\n"
            f"Доступно: {u['balance']:.2f} USDT\n"
            f"В стейкинге: {u['staked_balance']:.2f} USDT\n"
            f"Активные стейки: {active}",
            reply_markup=wallet_menu(),
        )
        return

    if q.data == "wallet_deposit":
        kb = InlineKeyboardMarkup([
            [btn("Crypto Bot", "deposit_method:cryptobot"), btn("Telegram Stars", "deposit_method:stars")],
            [btn("🔴 Назад", "menu_wallet")],
        ])
        await q.edit_message_text("Выберите метод пополнения:", reply_markup=kb)
        return

    if q.data.startswith("deposit_method:"):
        method = q.data.split(":", 1)[1]
        context.user_data["deposit_method"] = method
        context.user_data["state"] = "await_deposit_amount"
        await q.edit_message_text(
            f"Введите сумму пополнения в USDT через {'Crypto Bot' if method == 'cryptobot' else 'Telegram Stars'}:",
            reply_markup=back_button("menu_wallet"),
        )
        return

    if q.data == "wallet_withdraw":
        context.user_data["state"] = "await_withdraw_amount"
        await q.edit_message_text(
            f"Введите сумму вывода (минимум {SETTINGS.min_withdraw_usdt} USDT):",
            reply_markup=back_button("menu_wallet"),
        )
        return

    if q.data.startswith("confirm_withdraw:"):
        amount = float(q.data.split(":", 1)[1])
        u = db.get_user(uid)
        if u["balance"] < amount:
            await q.edit_message_text("Недостаточно средств для вывода.", reply_markup=wallet_menu())
            return
        db.update_balance(uid, delta_balance=-amount)
        db.add_transaction(uid, "withdraw", amount, "USDT", "processing", completed=False)
        await q.edit_message_text("✅ Заявка на вывод создана.", reply_markup=wallet_menu())
        return

    if q.data == "wallet_stake":
        kb = InlineKeyboardMarkup(
            [[btn(p.title, f"stake_plan:{p.key}")] for p in SETTINGS.plans.values()]
            + [[btn("🔴 Назад", "menu_wallet")]]
        )
        await q.edit_message_text("Выберите план стейкинга:", reply_markup=kb)
        return

    if q.data.startswith("stake_plan:"):
        context.user_data["stake_plan"] = q.data.split(":", 1)[1]
        context.user_data["state"] = "await_stake_amount"
        await q.edit_message_text("Введите сумму для стейкинга:", reply_markup=back_button("menu_wallet"))
        return

    if q.data.startswith("confirm_stake:"):
        amount = float(q.data.split(":", 1)[1])
        plan = SETTINGS.plans[context.user_data["stake_plan"]]
        u = db.get_user(uid)
        if u["balance"] < amount:
            await q.edit_message_text("Недостаточно средств.", reply_markup=wallet_menu())
            return
        income = round(amount * (plan.percent / 100), 8)
        end_time = (datetime.utcnow() + timedelta(days=plan.days)).isoformat(sep=" ", timespec="seconds")
        db.update_balance(uid, delta_balance=-amount, delta_staked=amount)
        db.create_stake(uid, plan.key, amount, income, end_time)
        db.add_transaction(uid, "stake", amount, "USDT", "successful")
        await q.edit_message_text(
            f"✅ Стейк активирован\n"
            f"План: {plan.title}\n"
            f"Сумма: {amount:.2f} USDT\n"
            f"Доход: {income:.2f} USDT\n"
            f"К получению: {amount + income:.2f} USDT\n"
            f"Окончание: {end_time} UTC",
            reply_markup=wallet_menu(),
        )
        return

    if q.data == "wallet_history":
        txs = db.list_recent_transactions(uid)
        if not txs:
            lines = ["История пуста"]
        else:
            lines = [
                f"• {t['type']} | {t['amount']:.2f} {t['currency']} | {t['created_at']} | {t['status']}"
                for t in txs
            ]
        await q.edit_message_text("\n".join(lines), reply_markup=back_button("menu_wallet"))
        return

    if q.data == "menu_refs":
        u = db.get_user(uid)
        refs, earned = db.get_ref_stats(uid)
        txt = (
            f"Ваша реферальная ссылка:\n{SETTINGS.base_ref_url}{u['referral_code']}\n\n"
            f"Рефералов: {refs}\n"
            f"Заработано на рефералах: {earned:.2f} USDT\n"
            f"Бонус: {SETTINGS.referral_percent}% от депозитов рефералов"
        )
        await q.edit_message_text(txt, reply_markup=back_button())


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")
    if not state:
        return

    uid = update.effective_user.id
    try:
        amount = float(update.message.text.replace(",", "."))
    except ValueError:
        await update.message.reply_text("Введите корректное число.")
        return

    if state == "await_deposit_amount":
        if amount < SETTINGS.min_deposit_usdt:
            await update.message.reply_text(f"Минимум: {SETTINGS.min_deposit_usdt} USDT")
            return
        method = context.user_data.get("deposit_method", "cryptobot")
        db.update_balance(uid, delta_balance=amount)
        db.add_transaction(uid, "deposit", amount, "USDT", f"successful:{method}")
        db.add_ref_bonus_for_deposit(uid, amount, SETTINGS.referral_percent)
        await update.message.reply_text(f"✅ Пополнение успешно: +{amount:.2f} USDT", reply_markup=main_menu())

    elif state == "await_withdraw_amount":
        u = db.get_user(uid)
        if amount < SETTINGS.min_withdraw_usdt:
            await update.message.reply_text(f"Минимум: {SETTINGS.min_withdraw_usdt} USDT")
            return
        if u["balance"] < amount:
            await update.message.reply_text("Недостаточно средств.")
            return
        kb = InlineKeyboardMarkup([
            [btn("✅ Подтвердить", f"confirm_withdraw:{amount}"), btn("❌ Отмена", "menu_wallet")],
        ])
        await update.message.reply_text(f"Подтвердите вывод {amount:.2f} USDT", reply_markup=kb)
        context.user_data["state"] = None
        return

    elif state == "await_stake_amount":
        plan = SETTINGS.plans[context.user_data["stake_plan"]]
        u = db.get_user(uid)
        if amount < SETTINGS.min_stake_usdt:
            await update.message.reply_text(f"Минимальный стейк: {SETTINGS.min_stake_usdt} USDT")
            return
        if u["balance"] < amount:
            await update.message.reply_text("Недостаточно средств.")
            return
        income = round(amount * (plan.percent / 100), 8)
        kb = InlineKeyboardMarkup([
            [btn("✅ Подтвердить", f"confirm_stake:{amount}"), btn("❌ Отмена", "menu_wallet")],
        ])
        await update.message.reply_text(
            f"Подтвердите стейкинг\nПлан: {plan.title}\nСумма: {amount:.2f} USDT\n"
            f"Ожидаемый доход: {income:.2f} USDT\nК получению: {amount + income:.2f} USDT",
            reply_markup=kb,
        )
        context.user_data["state"] = None
        return

    context.user_data["state"] = None


def run():
    db.init_db()
    app = Application.builder().token(SETTINGS.bot_token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(db.process_finished_stakes, "interval", seconds=30)
    scheduler.start()

    app.run_polling()


if __name__ == "__main__":
    run()
