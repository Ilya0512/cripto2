from datetime import UTC, datetime, timedelta
from pathlib import Path

import aiogram
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.filters.command import CommandObject
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, InputFile, Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot import db
from bot.config import SETTINGS

try:
    from aiogram.enums import ButtonStyle
except ImportError:  # pragma: no cover
    from aiogram.enums.button_style import ButtonStyle

try:
    from aiogram.types import CopyTextButton
except ImportError:  # pragma: no cover
    CopyTextButton = None

router = Router()
user_states: dict[int, dict[str, str]] = {}
WELCOME_TEXT = "🏠 Добро пожаловать!\nИнвестируйте и зарабатывайте с нашим проектом."
BOT_USERNAME_RUNTIME: str = ""


PLAN_TRANSLATIONS = {"daily": "Дневной", "weekly": "Недельный", "monthly": "Месячный"}
TX_TRANSLATIONS = {
    "deposit": "Пополнение",
    "withdraw": "Вывод",
    "stake": "Стейкинг",
    "referral_bonus": "Реф. бонус",
    "stake_profit": "Доход стейкинга",
}


def kb(rows: list[list[InlineKeyboardButton | dict]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def styled_button(text: str, *, callback_data: str | None = None, style: ButtonStyle | None = None, url: str | None = None) -> InlineKeyboardButton | dict:
    kwargs = {"text": text}
    if callback_data:
        kwargs["callback_data"] = callback_data
    if url:
        kwargs["url"] = url
    if style is not None:
        kwargs["style"] = style
    try:
        return InlineKeyboardButton(**kwargs)
    except TypeError:
        if style is not None:
            kwargs["style"] = str(style.value if hasattr(style, "value") else style).lower()
        return kwargs


def copy_button(text: str, value: str) -> InlineKeyboardButton | dict:
    if CopyTextButton is not None:
        try:
            return InlineKeyboardButton(text=text, copy_text=CopyTextButton(text=value))
        except TypeError:
            pass
    return {"text": text, "copy_text": {"text": value}}


def back_btn(target: str = "back_main") -> InlineKeyboardButton | dict:
    return styled_button("← Назад", callback_data=target, style=ButtonStyle.DANGER)


def main_menu_kb() -> InlineKeyboardMarkup:
    return kb([
        [styled_button("Кошелек", callback_data="menu_wallet"), styled_button("Информация", callback_data="menu_info")],
        [styled_button("Чат", url=f"https://t.me/{SETTINGS.support_username}"), styled_button("Рефералы", callback_data="menu_referrals")],
    ])


def wallet_kb() -> InlineKeyboardMarkup:
    return kb([
        [styled_button("Пополнить", callback_data="wallet_deposit", style=ButtonStyle.SUCCESS), styled_button("Вывести", callback_data="wallet_withdraw", style=ButtonStyle.DANGER)],
        [styled_button("Стейкинг", callback_data="wallet_stake", style=ButtonStyle.PRIMARY), styled_button("История", callback_data="wallet_history", style=ButtonStyle.PRIMARY)],
        [back_btn("wallet_back")],
    ])


def status_emoji(status: str) -> str:
    return {"pending": "⏳", "completed": "✅", "failed": "❌"}.get(status, "⏳")


def referral_link(ref_code: str) -> str:
    return f"https://t.me/{BOT_USERNAME_RUNTIME}?start={ref_code}"


async def delete_current_message(message: Message) -> None:
    try:
        await message.delete()
    except Exception:
        pass


async def send_banner_or_text(message: Message) -> None:
    banner_path = Path(SETTINGS.banner_path)
    if SETTINGS.banner_path and banner_path.exists() and banner_path.is_file():
        photo: InputFile = FSInputFile(str(banner_path))
        await message.answer_photo(photo=photo, caption=WELCOME_TEXT, reply_markup=main_menu_kb())
        return
    await message.answer(WELCOME_TEXT, reply_markup=main_menu_kb())


async def open_section(q: CallbackQuery, text: str, markup: InlineKeyboardMarkup) -> None:
    await delete_current_message(q.message)
    await q.message.answer(text, reply_markup=markup)


@router.message(CommandStart(deep_link=True))
@router.message(CommandStart())
async def start_handler(message: Message, command: CommandObject) -> None:
    ref_code = command.args if command and command.args else None
    db.ensure_user(message.from_user, ref_code)
    await send_banner_or_text(message)


@router.callback_query()
async def callbacks(q: CallbackQuery) -> None:
    await q.answer()
    uid = q.from_user.id
    db.ensure_user(q.from_user)
    user_state = user_states.setdefault(uid, {})

    if q.data in {"back_main", "wallet_back"}:
        user_state.clear()
        await delete_current_message(q.message)
        await send_banner_or_text(q.message)
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
        await open_section(q, txt, kb([[back_btn()]]))
    elif q.data == "menu_wallet":
        u = db.get_user(uid)
        txt = (
            "💰 Ваш кошелек\n\n"
            f"💵 Доступный баланс: {u['balance']:.2f} USDT\n"
            f"🔒 В стейкинге: {u['staked_balance']:.2f} USDT\n"
            f"📊 Активных стейков: {db.get_active_stakes_count(uid)}\n\n"
            "Выберите действие:"
        )
        await open_section(q, txt, wallet_kb())
    elif q.data == "wallet_deposit":
        await open_section(q, "💼 Пополнение баланса\n\nВыберите способ пополнения:", kb([
            [styled_button("Crypto Bot", callback_data="deposit_crypto")],
            [styled_button("Telegram Stars", callback_data="deposit_stars")],
            [back_btn("menu_wallet")],
        ]))
    elif q.data in {"deposit_crypto", "deposit_stars"}:
        user_state["state"] = "await_deposit"
        user_state["deposit_method"] = "cryptobot" if q.data == "deposit_crypto" else "stars"
        await open_section(q, f"Введите сумму пополнения (минимум {SETTINGS.min_deposit_usdt:g} USDT):", kb([[back_btn("menu_wallet")]]))
    elif q.data == "wallet_withdraw":
        user_state["state"] = "await_withdraw"
        u = db.get_user(uid)
        await open_section(q, f"📤 Вывод средств\n\n💰 Ваш баланс: {u['balance']:.2f} USDT\nМинимальная сумма вывода: {SETTINGS.min_withdraw_usdt:g} USDT\n\nВведите сумму для вывода:", kb([[back_btn("menu_wallet")]]))
    elif q.data == "wallet_stake":
        await open_section(
            q,
            "📊 Стейкинг\n\n📅 Дневной план\n• Срок: 1 день\n• Доход: +1%\n\n📅 Недельный план\n• Срок: 7 дней\n• Доход: +5%\n\n📈 Месячный план\n• Срок: 10 дней\n• Доход: +10%\n\nВыберите план:",
            kb([
                [styled_button("Дневной", callback_data="staking_daily"), styled_button("Недельный", callback_data="staking_weekly")],
                [styled_button("Месячный", callback_data="staking_monthly"), styled_button("Мои стейки", callback_data="staking_my")],
                [back_btn("menu_wallet")],
            ]),
        )
    elif q.data in {"staking_daily", "staking_weekly", "staking_monthly"}:
        plan = q.data.split("_")[1]
        user_state["state"] = "await_stake"
        user_state["stake_plan"] = plan
        p = SETTINGS.plans[plan]
        await open_section(q, f"📊 {p.title} план\nПериод: {p.days} дн.\nДоход: +{p.percent}%\n\nВведите сумму:", kb([[back_btn("wallet_stake")]]))
    elif q.data == "staking_my":
        rows = db.list_active_stakes(uid)
        if not rows:
            txt = "📭 У вас пока нет активных стейков."
        else:
            stake_lines = []
            for s in rows:
                title = PLAN_TRANSLATIONS.get(s["plan"], s["plan"])
                stake_lines.append(
                    f"• {title}\n  Сумма: {s['amount']:.2f} USDT\n  Доход: {s['profit']:.2f} USDT\n  Завершится: {s['end_time']}"
                )
            txt = "📊 Ваши активные стейки:\n\n" + "\n\n".join(stake_lines)
        await open_section(q, txt, kb([[back_btn("wallet_stake")]]))
    elif q.data == "wallet_history":
        txs = db.list_recent_transactions(uid, 10)
        if not txs:
            txt = "📜 История пуста."
        else:
            items = []
            for t in txs:
                title = TX_TRANSLATIONS.get(t["type"], t["type"].title())
                items.append(f"{status_emoji(t['status'])} {title}: {t['amount']:.2f} {t['currency']}\n{t['created_at']}")
            txt = "📜 Последние транзакции:\n\n" + "\n\n".join(items)
        await open_section(q, txt, kb([[back_btn("menu_wallet")]]))
    elif q.data == "menu_referrals":
        u = db.get_user(uid)
        with db.conn() as c:
            refs = c.execute("SELECT COUNT(*) c FROM users WHERE referrer_id=?", (uid,)).fetchone()["c"]
        link = referral_link(u["referral_code"])
        txt = (
            "👥 Реферальная программа\n\n"
            f"🎁 Получайте {SETTINGS.referral_percent:g}% от депозитов ваших рефералов!\n\n"
            "📊 Ваша статистика:\n"
            f"• Рефералов: {refs}\n"
            f"• Заработано: {u['referral_earned']:.2f} USDT\n\n"
            "🔗 Ваша реферальная ссылка:\n"
            f"{link}\n\n"
            "Делитесь ссылкой с друзьями и зарабатывайте!"
        )
        await open_section(q, txt, kb([[copy_button("Скопировать", link)], [back_btn()]]))


@router.message(F.text)
async def amount_input(message: Message) -> None:
    uid = message.from_user.id
    state = user_states.setdefault(uid, {})
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
        end_dt = datetime.now(UTC) + timedelta(days=plan.days)
        end = end_dt.strftime("%Y-%m-%d %H:%M:%S")
        db.update_balance(uid, delta_balance=-amount, delta_staked=amount)
        db.create_stake(uid, plan.key, amount, plan.percent, profit, round(amount + profit, 2), end)
        db.add_transaction(uid, "stake", amount, status="completed", completed=True, meta={"plan": plan.key})
        state.clear()
        await message.answer(f"✅ Подтверждение стейка\n\nСумма: {amount:.2f} USDT\nДоход: +{profit:.2f} USDT\nДата окончания: {end}")


async def main() -> None:
    global BOT_USERNAME_RUNTIME
    print("Aiogram version:", aiogram.__version__)
    if tuple(map(int, aiogram.__version__.split("."))) < (3, 27, 0):
        print("Для цветных кнопок нужен aiogram >= 3.27.0. Выполните: pip install -U aiogram")

    db.init_db()
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(db.process_finished_stakes, "interval", minutes=1)
    scheduler.start()

    bot = Bot(token=SETTINGS.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    me = await bot.get_me()
    BOT_USERNAME_RUNTIME = SETTINGS.bot_username or ""
    if not BOT_USERNAME_RUNTIME:
        BOT_USERNAME_RUNTIME = me.username or ""
    if not BOT_USERNAME_RUNTIME or " " in BOT_USERNAME_RUNTIME or BOT_USERNAME_RUNTIME.startswith("@"):
        BOT_USERNAME_RUNTIME = me.username or ""

    dp = Dispatcher()
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
