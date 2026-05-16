from datetime import UTC, datetime, timedelta
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.filters.command import CommandObject
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot import db
from bot.config import SETTINGS

router = Router()


def kb(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def style_btn(text: str, callback_data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=callback_data)


def back_btn(target: str = "back_main") -> InlineKeyboardButton:
    return style_btn("← Назад", target)


def main_menu_kb() -> InlineKeyboardMarkup:
    return kb([
        [InlineKeyboardButton(text="Кошелек", callback_data="menu_wallet"), InlineKeyboardButton(text="Информация", callback_data="menu_info")],
        [InlineKeyboardButton(text="Чат", callback_data="menu_chat"), InlineKeyboardButton(text="Рефералы", callback_data="menu_referrals")],
    ])


def wallet_kb() -> InlineKeyboardMarkup:
    return kb([
        [style_btn("Пополнить", "wallet_deposit"), style_btn("Вывести", "wallet_withdraw")],
        [style_btn("Стейкинг", "wallet_staking"), style_btn("История", "wallet_history")],
        [back_btn("back_main")],
    ])


def status_emoji(status: str) -> str:
    return {"pending": "⏳", "completed": "✅", "failed": "❌"}.get(status, "⏳")


async def send_banner_or_text(message: Message, text: str, markup: InlineKeyboardMarkup) -> None:
    banner_path = Path(SETTINGS.banner_path)
    if SETTINGS.banner_path and banner_path.exists() and banner_path.is_file():
        await message.answer_photo(photo=FSInputFile(str(banner_path)), caption=text, reply_markup=markup)
        return
    await message.answer(text, reply_markup=markup)


@router.message(CommandStart(deep_link=True))
@router.message(CommandStart())
async def start_handler(message: Message, command: CommandObject) -> None:
    ref_code = command.args if command and command.args else None
    db.ensure_user(message.from_user, ref_code)
    await send_banner_or_text(
        message,
        "🏠 Добро пожаловать!\nИнвестируйте и зарабатывайте с нашим проектом.",
        main_menu_kb(),
    )


@router.callback_query()
async def callbacks(q: CallbackQuery) -> None:
    await q.answer()
    uid = q.from_user.id
    db.ensure_user(q.from_user)
    state = q.bot.session.middleware_data.setdefault("states", {})
    user_state = state.setdefault(uid, {})

    if q.data == "back_main":
        user_state.clear()
        await q.message.answer("🏠 Добро пожаловать!\nИнвестируйте и зарабатывайте с нашим проектом.", reply_markup=main_menu_kb())
    elif q.data == "menu_info":
        txt = (
            "ℹ️ Информация о проекте\n\n"
            "📅 Планы стейкинга:\n"
            "• Дневной: 1 день, +1%\n"
            "• Недельный: 7 дней, +5%\n"
            "• Месячный: 10 дней, +10%\n\n"
            f"Минимум пополнения: {SETTINGS.min_deposit_usdt:g} USDT\n"
            f"Минимум стейкинга: {SETTINGS.min_stake_usdt:g} USDT\n"
            f"Минимум вывода: {SETTINGS.min_withdraw_usdt:g} USDT\n"
            f"Реферальный процент: {SETTINGS.referral_percent:g}%\n\n"
            f"Поддержка: @{SETTINGS.support_username}"
        )
        await q.message.edit_text(txt, reply_markup=kb([[back_btn()]]))
    elif q.data == "menu_wallet":
        u = db.get_user(uid)
        txt = (
            "💰 Ваш кошелек\n\n"
            f"💵 Доступный баланс: {u['balance']:.2f} USDT\n"
            f"🔒 В стейкинге: {u['staked_balance']:.2f} USDT\n"
            f"📊 Активных стейков: {db.get_active_stakes_count(uid)}\n\n"
            "Выберите действие:"
        )
        await q.message.edit_text(txt, reply_markup=wallet_kb())
    elif q.data == "wallet_deposit":
        await q.message.edit_text("💼 Пополнение баланса\n\nВыберите способ пополнения:", reply_markup=kb([
            [InlineKeyboardButton(text="Crypto Bot", callback_data="deposit_crypto")],
            [InlineKeyboardButton(text="Telegram Stars", callback_data="deposit_stars")],
            [back_btn("menu_wallet")],
        ]))
    elif q.data in {"deposit_crypto", "deposit_stars"}:
        user_state["state"] = "await_deposit"
        user_state["deposit_method"] = "cryptobot" if q.data == "deposit_crypto" else "stars"
        await q.message.edit_text(f"Введите сумму пополнения (минимум {SETTINGS.min_deposit_usdt:g} USDT):", reply_markup=kb([[back_btn("menu_wallet")]]))
    elif q.data == "wallet_withdraw":
        user_state["state"] = "await_withdraw"
        u = db.get_user(uid)
        await q.message.edit_text(f"📤 Вывод средств\n\n💰 Ваш баланс: {u['balance']:.2f} USDT\nМинимальная сумма вывода: {SETTINGS.min_withdraw_usdt:g} USDT\n\nВведите сумму для вывода:", reply_markup=kb([[back_btn("menu_wallet")]]))
    elif q.data == "wallet_staking":
        await q.message.edit_text(
            "📊 Стейкинг\n\n📅 Дневной план\n• Срок: 1 день\n• Доход: +1%\n\n📅 Недельный план\n• Срок: 7 дней\n• Доход: +5%\n\n📈 Месячный план\n• Срок: 10 дней\n• Доход: +10%\n\nВыберите план:",
            reply_markup=kb([
                [InlineKeyboardButton(text="Дневной", callback_data="staking_daily"), InlineKeyboardButton(text="Недельный", callback_data="staking_weekly")],
                [InlineKeyboardButton(text="Месячный", callback_data="staking_monthly"), InlineKeyboardButton(text="Мои стейки", callback_data="staking_my")],
                [back_btn("menu_wallet")],
            ]),
        )
    elif q.data in {"staking_daily", "staking_weekly", "staking_monthly"}:
        plan = q.data.split("_")[1]
        user_state["state"] = "await_stake"
        user_state["stake_plan"] = plan
        p = SETTINGS.plans[plan]
        await q.message.edit_text(f"📊 {p.title} план\nПериод: {p.days} дн.\nДоход: +{p.percent}%\n\nВведите сумму:", reply_markup=kb([[back_btn("wallet_staking")]]))
    elif q.data == "staking_my":
        rows = db.list_active_stakes(uid)
        txt = "📭 У вас пока нет активных стейков." if not rows else "\n".join(["📊 Ваши активные стейки:"] + [f"• {s['plan']} | {s['amount']:.2f} USDT | +{s['profit']:.2f} | до {s['end_time']}" for s in rows])
        await q.message.edit_text(txt, reply_markup=kb([[back_btn("wallet_staking")]]))
    elif q.data == "wallet_history":
        txs = db.list_recent_transactions(uid, 10)
        txt = "📜 История пуста." if not txs else "\n".join(["📜 Последние транзакции:"] + [f"{status_emoji(t['status'])} {t['type'].title()}: {t['amount']:.2f} {t['currency']} ({t['created_at']})" for t in txs])
        await q.message.edit_text(txt, reply_markup=kb([[back_btn("menu_wallet")]]))
    elif q.data == "menu_referrals":
        u = db.get_user(uid)
        with db.conn() as c:
            refs = c.execute("SELECT COUNT(*) c FROM users WHERE referrer_id=?", (uid,)).fetchone()["c"]
        link = f"https://t.me/{SETTINGS.bot_username}?start={u['referral_code']}"
        txt = f"👥 Реферальная программа\n\nРефералов: {refs}\nЗаработано: {u['referral_earned']:.2f} USDT\n\n🔗 {link}"
        await q.message.edit_text(txt, reply_markup=kb([[InlineKeyboardButton(text="Скопировать", callback_data="referrals_copy")], [back_btn()]]))
    elif q.data == "referrals_copy":
        u = db.get_user(uid)
        await q.message.answer(f"https://t.me/{SETTINGS.bot_username}?start={u['referral_code']}")
    elif q.data == "menu_chat":
        await q.message.edit_text(f"💬 Поддержка: @{SETTINGS.support_username}", reply_markup=kb([[InlineKeyboardButton(text="Открыть чат", url=f"https://t.me/{SETTINGS.support_username}")], [back_btn()]]))


@router.message(F.text)
async def amount_input(message: Message) -> None:
    uid = message.from_user.id
    state = message.bot.session.middleware_data.setdefault("states", {}).setdefault(uid, {})
    step = state.get("state")
    if not step:
        return
    try:
        amount = float(message.text.replace(",", "."))
    except ValueError:
        await message.answer("Введите корректное число.")
        return

    user = db.get_user(uid)
    if step == "await_deposit":
        if amount < SETTINGS.min_deposit_usdt:
            await message.answer(f"Минимальная сумма пополнения: {SETTINGS.min_deposit_usdt:g} USDT")
            return
        tx = db.add_transaction(uid, "deposit", amount, status="pending", meta={"method": state.get("deposit_method")})
        db.complete_transaction(tx)
        db.update_balance(uid, delta_balance=amount)
        db.apply_referral_bonus_if_needed(uid, amount, SETTINGS.referral_percent)
        state.clear()
        await message.answer(f"✅ Пополнение подтверждено: +{amount:.2f} USDT")
    elif step == "await_withdraw":
        if amount < SETTINGS.min_withdraw_usdt:
            await message.answer(f"Минимальная сумма вывода: {SETTINGS.min_withdraw_usdt:g} USDT")
            return
        if amount > user["balance"]:
            await message.answer("Недостаточно средств.")
            return
        db.update_balance(uid, delta_balance=-amount)
        db.add_transaction(uid, "withdraw", amount, status="pending", meta={"note": "manual"})
        state.clear()
        await message.answer("✅ Заявка на вывод создана.")
    elif step == "await_stake":
        if amount < SETTINGS.min_stake_usdt:
            await message.answer(f"Минимальная сумма стейкинга: {SETTINGS.min_stake_usdt:g} USDT")
            return
        if amount > user["balance"]:
            await message.answer("Недостаточно средств.")
            return
        plan = SETTINGS.plans[state["stake_plan"]]
        profit = round(amount * plan.percent / 100, 2)
        total = round(amount + profit, 2)
        end_dt = datetime.now(UTC) + timedelta(days=plan.days)
        end = end_dt.strftime("%Y-%m-%d %H:%M:%S")
        db.update_balance(uid, delta_balance=-amount, delta_staked=amount)
        db.create_stake(uid, plan.key, amount, plan.percent, profit, total, end)
        db.add_transaction(uid, "stake", amount, status="completed", completed=True, meta={"plan": plan.key})
        state.clear()
        await message.answer(
            f"✅ Подтверждение стейка\n\nСумма: {amount:.2f} USDT\nДоход: +{profit:.2f} USDT\nДата окончания: {end}"
        )


async def main() -> None:
    db.init_db()
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(db.process_finished_stakes, "interval", minutes=1)
    scheduler.start()

    bot = Bot(token=SETTINGS.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
