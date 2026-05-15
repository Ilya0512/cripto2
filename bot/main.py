from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from bot.config import SETTINGS
from bot import db


def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Кошелек", callback_data="menu_wallet")],
        [InlineKeyboardButton("Информация", callback_data="menu_info")],
        [InlineKeyboardButton("Чат", callback_data="menu_chat")],
        [InlineKeyboardButton("Рефералы", callback_data="menu_refs")],
    ])


def back_button():
    return InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="menu_main")]])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    referrer_id = None
    if context.args and context.args[0].startswith("ref"):
        referrer_id = int(context.args[0].replace("ref", ""))
    db.ensure_user(user.id, referrer_id)
    await update.message.reply_text(f"Добро пожаловать в {SETTINGS.project_name}", reply_markup=main_menu())


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    db.ensure_user(uid)

    if q.data == "menu_main":
        await q.edit_message_text("Главное меню", reply_markup=main_menu()); return
    if q.data == "menu_info":
        plans = "\n".join([f"• {p.title}: {p.days} дн, +{p.percent}%" for p in SETTINGS.plans.values()])
        txt = (
            f"{SETTINGS.project_name}\n\n"
            f"Пополнение: Crypto Pay / Telegram Stars\nВывод в криптовалюте\n"
            f"Стейкинг доходность 1%-10%\nРеф-бонус: {SETTINGS.referral_percent}%\n\n"
            f"Планы:\n{plans}\n\n"
            f"Минимумы:\nПополнение {SETTINGS.min_deposit_usdt} USDT\n"
            f"Стейкинг {SETTINGS.min_stake_usdt} USDT\nВывод {SETTINGS.min_withdraw_usdt} USDT\n"
            f"Поддержка: @{SETTINGS.support_username}"
        )
        await q.edit_message_text(txt, reply_markup=back_button()); return
    if q.data == "menu_chat":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Открыть чат", url=SETTINGS.support_chat_url)], [InlineKeyboardButton("Назад", callback_data="menu_main")]])
        await q.edit_message_text("Чат поддержки", reply_markup=kb); return
    if q.data == "menu_wallet":
        u = db.get_user(uid)
        active = db.get_active_stakes_count(uid)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Пополнить", callback_data="wallet_deposit")],
            [InlineKeyboardButton("Вывести", callback_data="wallet_withdraw")],
            [InlineKeyboardButton("Стейкинг", callback_data="wallet_stake")],
            [InlineKeyboardButton("История", callback_data="wallet_history")],
            [InlineKeyboardButton("Назад", callback_data="menu_main")],
        ])
        await q.edit_message_text(f"Баланс: {u['balance']:.2f} USDT\nВ стейкинге: {u['staked_balance']:.2f} USDT\nАктивные стейки: {active}", reply_markup=kb); return
    if q.data == "wallet_deposit":
        context.user_data["state"] = "await_deposit_amount"
        await q.edit_message_text("Введите сумму пополнения в USDT (демо-режим).", reply_markup=back_button()); return
    if q.data == "wallet_withdraw":
        context.user_data["state"] = "await_withdraw_amount"
        await q.edit_message_text(f"Введите сумму вывода (минимум {SETTINGS.min_withdraw_usdt} USDT)", reply_markup=back_button()); return
    if q.data == "wallet_stake":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(p.title, callback_data=f"stake_plan:{p.key}")] for p in SETTINGS.plans.values()] + [[InlineKeyboardButton("Назад", callback_data="menu_wallet")]])
        await q.edit_message_text("Выберите план стейкинга", reply_markup=kb); return
    if q.data.startswith("stake_plan:"):
        context.user_data["stake_plan"] = q.data.split(":",1)[1]
        context.user_data["state"] = "await_stake_amount"
        await q.edit_message_text("Введите сумму для стейкинга", reply_markup=back_button()); return
    if q.data == "wallet_history":
        txs = db.list_recent_transactions(uid)
        lines = [f"{t['type']} | {t['amount']} {t['currency']} | {t['created_at']} | {t['status']}" for t in txs] or ["История пуста"]
        await q.edit_message_text("\n".join(lines), reply_markup=back_button()); return
    if q.data == "menu_refs":
        u = db.get_user(uid)
        refs, earned = db.get_ref_stats(uid)
        txt = f"Ваша ссылка:\n{SETTINGS.base_ref_url}{u['referral_code']}\n\nРефералов: {refs}\nЗаработано: {earned:.2f} USDT\nБонус: {SETTINGS.referral_percent}%"
        await q.edit_message_text(txt, reply_markup=back_button()); return


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")
    if not state:
        return
    uid = update.effective_user.id
    try:
        amount = float(update.message.text.replace(",", "."))
    except ValueError:
        await update.message.reply_text("Введите число.")
        return

    if state == "await_deposit_amount":
        if amount < SETTINGS.min_deposit_usdt:
            await update.message.reply_text(f"Минимум: {SETTINGS.min_deposit_usdt} USDT"); return
        db.update_balance(uid, delta_balance=amount)
        db.add_transaction(uid, "deposit", amount, "USDT", "successful")
        await update.message.reply_text(f"Пополнение успешно: +{amount} USDT", reply_markup=main_menu())

    elif state == "await_withdraw_amount":
        u = db.get_user(uid)
        if amount < SETTINGS.min_withdraw_usdt:
            await update.message.reply_text(f"Минимум: {SETTINGS.min_withdraw_usdt} USDT"); return
        if u["balance"] < amount:
            await update.message.reply_text("Недостаточно средств."); return
        db.update_balance(uid, delta_balance=-amount)
        db.add_transaction(uid, "withdraw", amount, "USDT", "processing", completed=False)
        await update.message.reply_text("Заявка на вывод создана (в обработке).", reply_markup=main_menu())

    elif state == "await_stake_amount":
        plan = SETTINGS.plans[context.user_data["stake_plan"]]
        u = db.get_user(uid)
        if amount < SETTINGS.min_stake_usdt:
            await update.message.reply_text(f"Минимальный стейк: {SETTINGS.min_stake_usdt} USDT"); return
        if u["balance"] < amount:
            await update.message.reply_text("Недостаточно средств."); return
        income = round(amount * (plan.percent / 100), 8)
        end_time = (datetime.utcnow() + timedelta(days=plan.days)).isoformat(sep=" ", timespec="seconds")
        db.update_balance(uid, delta_balance=-amount, delta_staked=amount)
        db.create_stake(uid, plan.key, amount, income, end_time)
        db.add_transaction(uid, "stake", amount, "USDT", "successful")
        await update.message.reply_text(
            f"Стейк активирован: {plan.title}\nСумма: {amount} USDT\nДоход: {income} USDT\nОкончание: {end_time} UTC",
            reply_markup=main_menu()
        )

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
