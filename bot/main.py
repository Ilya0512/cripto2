from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
import asyncio

import aiogram
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.filters.command import CommandObject
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message
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
user_states: dict[int, dict] = {}
WELCOME_TEXT = "🏠 Добро пожаловать!\nИнвестируйте и зарабатывайте с нашим проектом."
BOT_USERNAME_RUNTIME: str = ""
EXPORTS_DIR = Path("exports")

PLAN_TRANSLATIONS = {"daily": "Дневной", "weekly": "Недельный", "monthly": "Месячный"}
TX_TRANSLATIONS = {
    "deposit": "Пополнение",
    "withdraw": "Вывод",
    "stake": "Стейкинг",
    "referral_bonus": "Реф. бонус",
    "stake_profit": "Доход стейкинга",
    "admin_credit": "Админ начисление",
    "admin_debit": "Админ списание",
}


def kb(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)


def styled_button(text: str, *, callback_data: str | None = None, style: ButtonStyle | None = None, url: str | None = None):
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
        return kwargs


def copy_button(text: str, value: str):
    if CopyTextButton is not None:
        try:
            return InlineKeyboardButton(text=text, copy_text=CopyTextButton(text=value))
        except TypeError:
            pass
    return {"text": text, "copy_text": {"text": value}}


def back_btn(target: str = "back_main"):
    return styled_button("← Назад", callback_data=target, style=ButtonStyle.DANGER)


def main_menu_kb(user_id: int | None = None) -> InlineKeyboardMarkup:
    rows = [
        [styled_button("Кошелек", callback_data="menu_wallet"), styled_button("Информация", callback_data="menu_info")],
        [styled_button("Чат", url=f"https://t.me/{SETTINGS.support_username}"), styled_button("Рефералы", callback_data="menu_referrals")],
    ]
    if user_id and db.is_admin(user_id):
        rows.append([styled_button("Админка", callback_data="admin_open", style=ButtonStyle.PRIMARY)])
    return kb(rows)


def wallet_kb() -> InlineKeyboardMarkup:
    return kb([
        [styled_button("Пополнить", callback_data="wallet_deposit", style=ButtonStyle.SUCCESS), styled_button("Вывести", callback_data="wallet_withdraw", style=ButtonStyle.DANGER)],
        [styled_button("Стейкинг", callback_data="wallet_stake", style=ButtonStyle.PRIMARY), styled_button("История", callback_data="wallet_history", style=ButtonStyle.PRIMARY)],
        [back_btn("wallet_back")],
    ])


def status_emoji(status: str) -> str:
    return {"pending": "⏳", "completed": "✅", "failed": "❌", "rejected": "❌"}.get(status, "⏳")


def referral_link(ref_code: str) -> str:
    return f"https://t.me/{BOT_USERNAME_RUNTIME}?start={ref_code}"


async def delete_message_safe(bot: Bot, chat_id: int, message_id: int) -> None:
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


async def send_message_safe(bot: Bot, chat_id: int, text: str, **kwargs):
    try:
        return await bot.send_message(chat_id=chat_id, text=text, **kwargs)
    except Exception:
        return None


async def send_document_safe(bot: Bot, chat_id: int, document, **kwargs):
    try:
        return await bot.send_document(chat_id=chat_id, document=document, **kwargs)
    except Exception:
        return None


async def send_photo_safe(bot: Bot, chat_id: int, photo, **kwargs):
    try:
        return await bot.send_photo(chat_id=chat_id, photo=photo, **kwargs)
    except Exception:
        return None


def get_main_banner_path() -> str:
    return SETTINGS.main_banner_path or SETTINGS.banner_path


async def send_section_with_banner(bot: Bot, chat_id: int, banner_path: str, caption: str, reply_markup=None, parse_mode=None):
    if banner_path:
        path = Path(banner_path)
        if path.exists() and path.is_file():
            return await send_photo_safe(bot, chat_id, FSInputFile(str(path)), caption=caption, reply_markup=reply_markup, parse_mode=parse_mode)
    return await send_message_safe(bot, chat_id, caption, reply_markup=reply_markup, parse_mode=parse_mode)


async def send_main_menu(bot: Bot, chat_id: int):
    return await send_section_with_banner(bot, chat_id, get_main_banner_path(), WELCOME_TEXT, main_menu_kb(chat_id))


async def open_section(q: CallbackQuery, text: str, markup: InlineKeyboardMarkup, banner_path: str = "") -> None:
    await delete_message_safe(q.bot, q.message.chat.id, q.message.message_id)
    await send_section_with_banner(q.bot, q.message.chat.id, banner_path, text, markup)


def admin_panel_content(uid: int):
    if db.is_main_admin(uid):
        return "👑 Админ-панель\n\nВыберите раздел:", kb([
            [styled_button("👥 Пользователи", callback_data="admin_users"), styled_button("📢 Рассылка", callback_data="admin_broadcast")],
            [styled_button("💸 Заявки на вывод", callback_data="admin_withdraws"), styled_button("📊 Статистика", callback_data="admin_stats")],
            [styled_button("🔎 Поиск пользователя", callback_data="admin_search"), styled_button("⚙️ Настройки", callback_data="admin_settings")],
            [styled_button("⬅️ В главное меню", callback_data="admin_exit_to_main")],
        ])
    return "🛠 Админ-панель\n\nВыберите раздел:", kb([
        [styled_button("👥 Пользователи", callback_data="admin_users"), styled_button("💸 Заявки на вывод", callback_data="admin_withdraws")],
        [styled_button("📊 Статистика", callback_data="admin_stats"), styled_button("🔎 Поиск пользователя", callback_data="admin_search")],
        [styled_button("⬅️ В главное меню", callback_data="admin_exit_to_main")],
    ])


def deny_rights():
    return "⛔ Недостаточно прав."


def parse_meta(raw):
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def broadcast_audience_ids(audience: str) -> list[int]:
    with db.conn() as c:
        if audience == "all":
            rows = c.execute("SELECT user_id FROM users WHERE COALESCE(is_blocked,0)=0").fetchall()
        elif audience == "depositors":
            rows = c.execute("SELECT DISTINCT u.user_id FROM users u JOIN transactions t ON t.user_id=u.user_id WHERE t.type='deposit' AND t.status='completed' AND COALESCE(u.is_blocked,0)=0").fetchall()
        elif audience == "stakers":
            rows = c.execute("SELECT DISTINCT u.user_id FROM users u JOIN stakes s ON s.user_id=u.user_id WHERE COALESCE(u.is_blocked,0)=0").fetchall()
        elif audience == "active_stakers":
            rows = c.execute("SELECT DISTINCT u.user_id FROM users u JOIN stakes s ON s.user_id=u.user_id WHERE s.status='active' AND COALESCE(u.is_blocked,0)=0").fetchall()
        elif audience == "no_deposits":
            rows = c.execute("SELECT u.user_id FROM users u WHERE COALESCE(u.is_blocked,0)=0 AND NOT EXISTS (SELECT 1 FROM transactions t WHERE t.user_id=u.user_id AND t.type='deposit' AND t.status='completed')").fetchall()
        else:
            rows = []
    return [r["user_id"] for r in rows]


def _write_export_file(filename: str, content: str) -> Path:
    EXPORTS_DIR.mkdir(exist_ok=True)
    path = EXPORTS_DIR / filename
    path.write_text(content, encoding="utf-8")
    return path


def admin_settings_kb():
    return kb([
        [styled_button("👮 Админы", callback_data="admin_admins")],
        [styled_button("📋 Текущие параметры", callback_data="admin_current_params")],
        [styled_button("⬅️ Назад", callback_data="admin_back")],
    ])


def admin_admins_kb():
    return kb([
        [styled_button("➕ Добавить админа", callback_data="admin_add_admin")],
        [styled_button("📋 Список админов", callback_data="admin_list_admins")],
        [styled_button("➖ Удалить админа", callback_data="admin_remove_admin")],
        [styled_button("⬅️ Назад", callback_data="admin_settings")],
    ])


def user_card(user):
    uid = user["user_id"]
    with db.conn() as c:
        active_stakes = c.execute("SELECT COUNT(*) c FROM stakes WHERE user_id=? AND status='active'", (uid,)).fetchone()["c"]
        deposited = c.execute("SELECT COALESCE(SUM(amount),0) s FROM transactions WHERE user_id=? AND type='deposit' AND status='completed'", (uid,)).fetchone()["s"]
        withdrawn = c.execute("SELECT COALESCE(SUM(amount),0) s FROM transactions WHERE user_id=? AND type='withdraw' AND status='completed'", (uid,)).fetchone()["s"]
        refs = c.execute("SELECT COUNT(*) c FROM users WHERE referrer_id=?", (uid,)).fetchone()["c"]
        ref = c.execute("SELECT user_id, username FROM users WHERE user_id=?", (user["referrer_id"],)).fetchone() if user["referrer_id"] else None
    ref_txt = f"{ref['user_id']} / @{ref['username']}" if ref and ref['username'] else (str(ref['user_id']) if ref else "—")
    status = "Заблокирован" if user["is_blocked"] else "Активен"
    return (
        "👤 Пользователь\n\n"
        f"ID: {uid}\nUsername: @{user['username']}\nИмя: {user['first_name']}\nДата регистрации: {user['created_at']}\n\n"
        f"Баланс: {user['balance']:.2f} USDT\nВ стейкинге: {user['staked_balance']:.2f} USDT\nАктивных стейков: {active_stakes}\n\n"
        f"Всего пополнено: {deposited:.2f} USDT\nВсего выведено: {withdrawn:.2f} USDT\n\n"
        "Реферальная информация:\n"
        f"Пришел от: {ref_txt}\nПривел пользователей: {refs}\nЗаработано с рефералов: {user['referral_earned']:.2f} USDT\n\n"
        f"Статус: {status}"
    )


def user_card_kb(admin_id: int, target_id: int, blocked: bool):
    rows = [
        [styled_button("📜 История", callback_data=f"admin_user_history:{target_id}"), styled_button("📊 Стейки", callback_data=f"admin_user_stakes:{target_id}")],
        [styled_button("💸 Выводы", callback_data=f"admin_user_withdraws:{target_id}"), styled_button("👥 Рефералы", callback_data=f"admin_user_refs:{target_id}")],
    ]
    if db.is_main_admin(admin_id):
        rows.append([styled_button("➕ Начислить баланс", callback_data=f"admin_user_credit:{target_id}"), styled_button("➖ Списать баланс", callback_data=f"admin_user_debit:{target_id}")])
        rows.append([styled_button("✅ Разблокировать" if blocked else "🚫 Заблокировать", callback_data=f"admin_user_unblock:{target_id}" if blocked else f"admin_user_block:{target_id}")])
    rows.append([styled_button("⬅️ Назад", callback_data="admin_open")])
    return kb(rows)


@router.message(CommandStart(deep_link=True))
@router.message(CommandStart())
async def start_handler(message: Message, command: CommandObject) -> None:
    ref_code = command.args if command and command.args else None
    db.ensure_user(message.from_user, ref_code)
    if db.is_user_blocked(message.from_user.id):
        return
    await send_main_menu(message.bot, message.chat.id)


@router.message(aiogram.filters.Command("admin"))
async def admin_cmd(message: Message):
    db.ensure_user(message.from_user)
    if db.is_user_blocked(message.from_user.id):
        return
    if not db.is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа к админ-панели.")
        return
    db.log_admin(message.from_user.id, "admin_open")
    text, markup = admin_panel_content(message.from_user.id)
    await message.answer(text, reply_markup=markup)


@router.callback_query()
async def callbacks(q: CallbackQuery) -> None:
    uid = q.from_user.id
    db.ensure_user(q.from_user)
    if db.is_user_blocked(uid):
        return
    await q.answer()
    state = user_states.setdefault(uid, {})

    if q.data == "admin_open":
        if not db.is_admin(uid):
            await q.answer(deny_rights(), show_alert=True)
            return
        db.log_admin(uid, "admin_open")
        await open_section(q, *admin_panel_content(uid))
        return
    if q.data == "admin_exit_to_main":
        state.clear()
        await delete_message_safe(q.bot, q.message.chat.id, q.message.message_id)
        await send_main_menu(q.bot, q.message.chat.id)
        return
    if q.data == "admin_back":
        await open_section(q, *admin_panel_content(uid))
        return

    if q.data == "admin_stats" or q.data == "admin_stats_refresh":
        with db.conn() as c:
            u_all = c.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
            depu = c.execute("SELECT COUNT(DISTINCT user_id) c FROM transactions WHERE type='deposit' AND status='completed'").fetchone()["c"]
            act = c.execute("SELECT COUNT(DISTINCT user_id) c FROM stakes WHERE status='active'").fetchone()["c"]
            act_sum = c.execute("SELECT COALESCE(SUM(amount),0) s FROM stakes WHERE status='active'").fetchone()["s"]
            dep_count = c.execute("SELECT COUNT(*) c FROM transactions WHERE type='deposit' AND status='completed'").fetchone()["c"]
            dep_sum = c.execute("SELECT COALESCE(SUM(amount),0) s FROM transactions WHERE type='deposit' AND status='completed'").fetchone()["s"]
            wp = c.execute("SELECT COUNT(*) c FROM transactions WHERE type='withdraw' AND status='pending'").fetchone()["c"]
            wc = c.execute("SELECT COUNT(*) c FROM transactions WHERE type='withdraw' AND status='completed'").fetchone()["c"]
            wr = c.execute("SELECT COUNT(*) c FROM transactions WHERE type='withdraw' AND status IN ('rejected','failed')").fetchone()["c"]
            ref = c.execute("SELECT COALESCE(SUM(amount),0) s FROM transactions WHERE type='referral_bonus' AND status='completed'").fetchone()["s"]
        txt = f"📊 Статистика проекта\n\nПользователей всего: {u_all}\nПополнявших: {depu}\nС активным стейкингом: {act}\n\nВ активном стейкинге: {act_sum:.2f} USDT\nДепозитов всего: {dep_count}\nСумма депозитов: {dep_sum:.2f} USDT\n\nЗаявок на вывод:\nОжидают: {wp}\nВыполнено: {wc}\nОтклонено: {wr}\n\nРеферальных начислений: {ref:.2f} USDT"
        await open_section(q, txt, kb([[styled_button("🔄 Обновить", callback_data="admin_stats_refresh")], [styled_button("⬅️ Назад", callback_data="admin_back")]]))
        return

    if q.data == "admin_search":
        state.clear(); state["state"] = "waiting_user_search_query"
        await open_section(q, "🔎 Поиск пользователя\n\nВведите TG ID или username пользователя:", kb([[styled_button("⬅️ Назад", callback_data="admin_back")]]))
        return
    if q.data == "admin_users":
        await open_section(q, "👥 Пользователи\n\nВыберите выгрузку:", kb([
            [styled_button("📋 Все пользователи", callback_data="admin_users_all")],
            [styled_button("💰 Пополнявшие", callback_data="admin_users_depositors")],
            [styled_button("📊 Со стейкингом", callback_data="admin_users_stakers")],
            [styled_button("🔒 С активным стейкингом", callback_data="admin_users_active_stakers")],
            [styled_button("👥 С рефералами", callback_data="admin_users_referrers")],
            [styled_button("⬅️ Назад", callback_data="admin_back")],
        ]))
        return
    if q.data in {"admin_users_all", "admin_users_depositors", "admin_users_stakers", "admin_users_active_stakers", "admin_users_referrers"}:
        category = q.data.replace("admin_users_", "")
        with db.conn() as c:
            if category == "all":
                users = c.execute("SELECT * FROM users ORDER BY user_id").fetchall()
            elif category == "depositors":
                users = c.execute("SELECT u.* FROM users u WHERE EXISTS(SELECT 1 FROM transactions t WHERE t.user_id=u.user_id AND t.type='deposit' AND t.status='completed') ORDER BY u.user_id").fetchall()
            elif category == "stakers":
                users = c.execute("SELECT u.* FROM users u WHERE EXISTS(SELECT 1 FROM stakes s WHERE s.user_id=u.user_id) ORDER BY u.user_id").fetchall()
            elif category == "active_stakers":
                users = c.execute("SELECT u.* FROM users u WHERE EXISTS(SELECT 1 FROM stakes s WHERE s.user_id=u.user_id AND s.status='active') ORDER BY u.user_id").fetchall()
            else:
                users = c.execute("SELECT u.* FROM users u WHERE EXISTS(SELECT 1 FROM users x WHERE x.referrer_id=u.user_id) ORDER BY u.user_id").fetchall()
        if not users:
            await send_message_safe(q.bot, q.message.chat.id, "Нет данных для выгрузки.")
            return
        blocks = [f"ОТЧЕТ: {category.upper()}", f"Дата выгрузки: {db.now_str()}", f"Всего пользователей: {len(users)}", "", "=" * 50]
        for i, u in enumerate(users, 1):
            blocks.append(f"\n{i}) Пользователь\n")
            blocks.append(user_card(u))
            blocks.append("\n" + "-" * 50)
        path = _write_export_file(f"users_{category}_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.txt", "\n".join(blocks))
        await send_document_safe(q.bot, q.message.chat.id, FSInputFile(str(path)))
        path.unlink(missing_ok=True)
        db.log_admin(uid, "export_users", details=f"category={category}")
        return
    if q.data == "admin_broadcast":
        if not db.is_main_admin(uid):
            await q.answer(deny_rights(), show_alert=True)
            return
        await open_section(q, "📢 Рассылка\n\nВыберите аудиторию:", kb([
            [styled_button("🌍 Всем", callback_data="admin_broadcast_all")],
            [styled_button("💰 Пополнявшим", callback_data="admin_broadcast_depositors")],
            [styled_button("📊 Со стейкингом", callback_data="admin_broadcast_stakers")],
            [styled_button("🔒 С активным стейкингом", callback_data="admin_broadcast_active_stakers")],
            [styled_button("😴 Без пополнений", callback_data="admin_broadcast_no_deposits")],
            [styled_button("⬅️ Назад", callback_data="admin_back")],
        ]))
        return
    if q.data in {"admin_broadcast_all", "admin_broadcast_depositors", "admin_broadcast_stakers", "admin_broadcast_active_stakers", "admin_broadcast_no_deposits"}:
        if not db.is_main_admin(uid):
            await q.answer(deny_rights(), show_alert=True)
            return
        audience = q.data.replace("admin_broadcast_", "")
        state.clear()
        state.update({"state": "waiting_broadcast_message", "broadcast_audience": audience})
        db.log_admin(uid, "broadcast_start", details=f"audience={audience}")
        await open_section(q, "Введите сообщение для рассылки.\n\nМожно отправить:\n• текст\n• фото\n• фото с подписью", kb([[styled_button("⬅️ Назад", callback_data="admin_back")]]))
        return
    if q.data == "admin_broadcast_cancel":
        state.clear()
        await open_section(q, "Рассылка отменена.", kb([[styled_button("⬅️ Назад", callback_data="admin_back")]]))
        return
    if q.data == "admin_broadcast_confirm":
        if not db.is_main_admin(uid):
            await q.answer(deny_rights(), show_alert=True)
            return
        recipients = state.get("broadcast_recipients", [])
        ok, err = 0, 0
        for rid in recipients:
            try:
                if state.get("broadcast_photo"):
                    await q.bot.send_photo(rid, state["broadcast_photo"], caption=state.get("broadcast_text") or None)
                else:
                    await q.bot.send_message(rid, state.get("broadcast_text") or "")
                ok += 1
            except Exception:
                err += 1
            await asyncio.sleep(0.06)
        db.log_admin(uid, "broadcast_finish", details=f"audience={state.get('broadcast_audience')};ok={ok};err={err}")
        audience = state.get("broadcast_audience", "all")
        total = ok + err
        state.clear()
        await open_section(q, f"📢 Рассылка завершена\n\nАудитория: {audience}\nПолучателей: {total}\nУспешно: {ok}\nОшибок: {err}", kb([[styled_button("⬅️ Назад", callback_data="admin_back")]]))
        return

    if q.data == "admin_settings":
        if not db.is_main_admin(uid):
            await q.answer(deny_rights(), show_alert=True)
            return
        await open_section(q, "⚙️ Настройки", admin_settings_kb())
        return
    if q.data == "admin_admins":
        if not db.is_main_admin(uid):
            await q.answer(deny_rights(), show_alert=True)
            return
        await open_section(q, "👮 Управление админами", admin_admins_kb())
        return
    if q.data == "admin_add_admin":
        if not db.is_main_admin(uid):
            await q.answer(deny_rights(), show_alert=True)
            return
        state.clear()
        state["state"] = "waiting_new_admin_id"
        await open_section(q, "Введите TG ID нового админа:", kb([[styled_button("⬅️ Назад", callback_data="admin_admins")]]))
        return
    if q.data == "admin_remove_admin":
        if not db.is_main_admin(uid):
            await q.answer(deny_rights(), show_alert=True)
            return
        state.clear()
        state["state"] = "waiting_remove_admin_id"
        await open_section(q, "Введите TG ID админа для удаления:", kb([[styled_button("⬅️ Назад", callback_data="admin_admins")]]))
        return
    if q.data == "admin_list_admins":
        if not db.is_main_admin(uid):
            await q.answer(deny_rights(), show_alert=True)
            return
        all_admins = db.get_all_admin_ids()
        regular = [x for x in all_admins if x != SETTINGS.main_admin_id]
        txt = (
            f"👑 Главный админ:\n{SETTINGS.main_admin_id}\n\n"
            "🛠 Обычные админы:\n"
            + ("\n".join(map(str, regular)) if regular else "—")
        )
        await open_section(q, txt, kb([[styled_button("⬅️ Назад", callback_data="admin_admins")]]))
        return
    if q.data == "admin_current_params":
        if not db.is_main_admin(uid):
            await q.answer(deny_rights(), show_alert=True)
            return
        txt = (
            "⚙️ Текущие параметры\n\n"
            f"MIN_DEPOSIT_USDT: {SETTINGS.min_deposit_usdt}\n"
            f"MIN_STAKE_USDT: {SETTINGS.min_stake_usdt}\n"
            f"MIN_WITHDRAW_USDT: {SETTINGS.min_withdraw_usdt}\n"
            f"REFERRAL_PERCENT: {SETTINGS.referral_percent}%\n"
            f"ADMIN_CAN_PROCESS_WITHDRAWS: {str(SETTINGS.admin_can_process_withdraws).lower()}\n"
            f"WITHDRAW_NOTIFY_ALL_ADMINS: {str(SETTINGS.withdraw_notify_all_admins).lower()}\n"
            f"Количество админов: {len(db.get_all_admin_ids())}"
        )
        await open_section(q, txt, kb([[styled_button("⬅️ Назад", callback_data="admin_settings")]]))
        return

    if q.data and q.data.startswith("admin_user_history:"):
        target = int(q.data.split(":")[1])
        txs = db.list_recent_transactions(target, 10)
        txt = "📜 История пуста." if not txs else "\n\n".join([f"{status_emoji(t['status'])} {TX_TRANSLATIONS.get(t['type'], t['type'])}: {t['amount']:.2f} {t['currency']}\n{t['created_at']}" for t in txs])
        await open_section(q, "📜 Последние 10 транзакций\n\n" + txt, kb([[styled_button("⬅️ Назад", callback_data=f"admin_user_card:{target}")]]))
        return

    if q.data and q.data.startswith("admin_user_stakes:"):
        target = int(q.data.split(":")[1])
        with db.conn() as c:
            rows = c.execute("SELECT * FROM stakes WHERE user_id=? ORDER BY id DESC LIMIT 20", (target,)).fetchall()
        if not rows:
            txt = "Стейки отсутствуют."
        else:
            txt = "\n\n".join(
                [
                    f"{PLAN_TRANSLATIONS.get(r['plan'], r['plan'])}\nСумма: {r['amount']:.2f} USDT\nДоход: {r['profit']:.2f} USDT\nСтатус: {r['status']}\nСтарт: {r['start_time']}\nКонец: {r['end_time']}"
                    for r in rows
                ]
            )
        await open_section(q, "📊 Стейки пользователя\n\n" + txt, kb([[styled_button("⬅️ Назад", callback_data=f"admin_user_card:{target}")]]))
        return

    if q.data and q.data.startswith("admin_user_withdraws:"):
        target = int(q.data.split(":")[1])
        with db.conn() as c:
            rows = c.execute("SELECT * FROM transactions WHERE user_id=? AND type='withdraw' ORDER BY id DESC LIMIT 20", (target,)).fetchall()
        if not rows:
            txt = "Выводы отсутствуют."
        else:
            txt = "\n\n".join(
                [
                    f"Сумма: {r['amount']:.2f} USDT\nАдрес: {parse_meta(r['meta']).get('address', '—')}\nСтатус: {r['status']}\nДата: {r['created_at']}"
                    for r in rows
                ]
            )
        await open_section(q, "💸 Выводы пользователя\n\n" + txt, kb([[styled_button("⬅️ Назад", callback_data=f"admin_user_card:{target}")]]))
        return

    if q.data and q.data.startswith("admin_user_refs:"):
        target = int(q.data.split(":")[1])
        with db.conn() as c:
            rows = c.execute("SELECT user_id, username, created_at FROM users WHERE referrer_id=? ORDER BY user_id", (target,)).fetchall()
        if not rows:
            txt = "Рефералов нет."
        else:
            txt = "\n".join([f"{r['user_id']} / @{r['username'] or '—'} / {r['created_at']}" for r in rows])
        await open_section(q, "👥 Рефералы пользователя\n\n" + txt, kb([[styled_button("⬅️ Назад", callback_data=f"admin_user_card:{target}")]]))
        return

    if q.data and q.data.startswith("admin_user_card:"):
        target = int(q.data.split(":")[1])
        user = db.get_user(target)
        if not user:
            await q.answer("Пользователь не найден", show_alert=True)
            return
        await open_section(q, user_card(user), user_card_kb(uid, target, bool(user["is_blocked"])))
        return

    if q.data and q.data.startswith("admin_user_credit:"):
        if not db.is_main_admin(uid):
            await q.answer(deny_rights(), show_alert=True); return
        target = int(q.data.split(":")[1]); state.clear(); state.update({"state": "waiting_credit_amount", "target_user": target})
        await open_section(q, "Введите сумму для начисления:", kb([[styled_button("❌ Отмена", callback_data="admin_back")]]))
        return

    if q.data and q.data.startswith("admin_user_debit:"):
        if not db.is_main_admin(uid):
            await q.answer(deny_rights(), show_alert=True); return
        target = int(q.data.split(":")[1]); state.clear(); state.update({"state": "waiting_debit_amount", "target_user": target})
        await open_section(q, "Введите сумму для списания:", kb([[styled_button("❌ Отмена", callback_data="admin_back")]]))
        return

    if q.data and q.data.startswith("admin_credit_confirm:"):
        if not db.is_main_admin(uid):
            await q.answer(deny_rights(), show_alert=True); return
        target = int(q.data.split(":")[1]); amount = float(state.get("pending_amount", 0)); user = db.get_user(target)
        db.update_balance(target, delta_balance=amount)
        db.add_transaction(target, "admin_credit", amount, status="completed", completed=True, meta={"admin_id": uid, "reason": "manual_admin_credit"})
        db.log_admin(uid, "admin_credit", "user", target, f"amount={amount:.2f}")
        await send_message_safe(q.bot, target, f"✅ На ваш баланс начислено {amount:.2f} USDT.")
        state.clear()
        await open_section(q, "✅ Баланс начислен.", kb([[styled_button("⬅️ Назад", callback_data="admin_back")]]))
        return

    if q.data and q.data.startswith("admin_debit_confirm:"):
        if not db.is_main_admin(uid):
            await q.answer(deny_rights(), show_alert=True); return
        target = int(q.data.split(":")[1]); amount = float(state.get("pending_amount", 0)); user = db.get_user(target)
        if user["balance"] < amount:
            await q.answer("Недостаточно средств у пользователя", show_alert=True); return
        db.update_balance(target, delta_balance=-amount)
        db.add_transaction(target, "admin_debit", amount, status="completed", completed=True, meta={"admin_id": uid, "reason": "manual_admin_debit"})
        db.log_admin(uid, "admin_debit", "user", target, f"amount={amount:.2f}")
        await send_message_safe(q.bot, target, f"С вашего баланса списано {amount:.2f} USDT.")
        state.clear()
        await open_section(q, "✅ Баланс списан.", kb([[styled_button("⬅️ Назад", callback_data="admin_back")]]))
        return

    if q.data == "admin_withdraws" or q.data in {"admin_withdraws_pending", "admin_withdraws_completed", "admin_withdraws_rejected"} or (q.data and q.data.startswith("admin_withdraw_page:")):
        status = "pending"
        page = 1
        if q.data == "admin_withdraws_completed":
            status = "completed"
        elif q.data == "admin_withdraws_rejected":
            status = "rejected"
        elif q.data and q.data.startswith("admin_withdraw_page:"):
            _, status, page = q.data.split(":"); page = int(page)
        with db.conn() as c:
            total = c.execute("SELECT COUNT(*) c FROM transactions WHERE type='withdraw' AND status IN (?,?)", (status, "failed" if status == "rejected" else status)).fetchone()["c"] if status == "rejected" else c.execute("SELECT COUNT(*) c FROM transactions WHERE type='withdraw' AND status=?", (status,)).fetchone()["c"]
            pages = max(1, (total + 4) // 5)
            page = max(1, min(page, pages))
            if status == "rejected":
                rows = c.execute("SELECT t.*, u.username, u.first_name FROM transactions t JOIN users u ON u.user_id=t.user_id WHERE t.type='withdraw' AND t.status IN ('rejected','failed') ORDER BY t.id DESC LIMIT 5 OFFSET ?", ((page-1)*5,)).fetchall()
            else:
                rows = c.execute("SELECT t.*, u.username, u.first_name FROM transactions t JOIN users u ON u.user_id=t.user_id WHERE t.type='withdraw' AND t.status=? ORDER BY t.id DESC LIMIT 5 OFFSET ?", (status, (page-1)*5)).fetchall()
        title = {"pending": "Ожидают", "completed": "Выполненные", "rejected": "Отклоненные"}[status]
        txt = ["💸 Заявки на вывод", "", f"Статус: {title}", f"Страница: {page} / {pages}", ""]
        for r in rows:
            meta = parse_meta(r["meta"])
            addr = meta.get("address", "—")
            txt.append(f"#{r['id']}\nПользователь: {r['user_id']} / @{r['username'] or '—'}\nИмя: {r['first_name'] or '—'}\nСумма: {r['amount']:.2f} USDT\nАдрес: {addr}\nДата: {r['created_at']}\nСтатус: {status_emoji(r['status'])} {r['status']}")
        btns = [[styled_button("⏳ Ожидают", callback_data="admin_withdraws_pending"), styled_button("✅ Выполненные", callback_data="admin_withdraws_completed")], [styled_button("❌ Отклоненные", callback_data="admin_withdraws_rejected"), styled_button("📄 Экспорт TXT", callback_data="admin_withdraw_export")]]
        if pages > 1:
            btns.append([styled_button("←", callback_data=f"admin_withdraw_page:{status}:{max(1,page-1)}"), styled_button(f"{page}/{pages}", callback_data="noop"), styled_button("→", callback_data=f"admin_withdraw_page:{status}:{min(pages,page+1)}")])
        if status == "pending":
            can_process = db.is_main_admin(uid) or SETTINGS.admin_can_process_withdraws
            for r in rows:
                btns.append([styled_button(f"✅ Выполнить #{r['id']}", callback_data=f"admin_withdraw_approve:{r['id']}"), styled_button(f"❌ Отклонить #{r['id']}", callback_data=f"admin_withdraw_reject:{r['id']}")])
            if not can_process and not db.is_main_admin(uid):
                pass
        btns.append([styled_button("⬅️ Назад", callback_data="admin_back")])
        await open_section(q, "\n\n".join(txt), kb(btns))
        return

    if q.data and q.data.startswith("admin_withdraw_approve:"):
        if not (db.is_main_admin(uid) or SETTINGS.admin_can_process_withdraws):
            await q.answer("Недостаточно прав для обработки заявки.", show_alert=True); return
        txid = int(q.data.split(":")[1])
        with db.conn() as c:
            t = c.execute("SELECT * FROM transactions WHERE id=? AND type='withdraw'", (txid,)).fetchone()
            if t and t["status"] == "pending":
                c.execute("UPDATE transactions SET status='completed', completed_at=? WHERE id=?", (db.now_str(), txid))
        if t:
            await send_message_safe(q.bot, t["user_id"], f"✅ Ваша заявка на вывод {t['amount']:.2f} USDT выполнена.")
            db.log_admin(uid, "withdraw_approve", "withdraw", txid, f"amount={t['amount']:.2f}")
        await open_section(q, "Заявка выполнена.", kb([[styled_button("⬅️ К заявкам", callback_data="admin_withdraws_pending")]]))
        return

    if q.data and q.data.startswith("admin_withdraw_reject:"):
        if not (db.is_main_admin(uid) or SETTINGS.admin_can_process_withdraws):
            await q.answer("Недостаточно прав для обработки заявки.", show_alert=True); return
        txid = int(q.data.split(":")[1])
        with db.conn() as c:
            t = c.execute("SELECT * FROM transactions WHERE id=? AND type='withdraw'", (txid,)).fetchone()
            if t and t["status"] == "pending":
                c.execute("UPDATE transactions SET status='rejected', completed_at=? WHERE id=?", (db.now_str(), txid))
                c.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (t["amount"], t["user_id"]))
        if t:
            await send_message_safe(q.bot, t["user_id"], f"❌ Ваша заявка на вывод {t['amount']:.2f} USDT отклонена. Средства возвращены на баланс.")
            db.log_admin(uid, "withdraw_reject", "withdraw", txid, f"amount={t['amount']:.2f}")
        await open_section(q, "Заявка отклонена.", kb([[styled_button("⬅️ К заявкам", callback_data="admin_withdraws_pending")]]))
        return
    if q.data == "admin_withdraw_export":
        with db.conn() as c:
            rows = c.execute("SELECT t.*, u.username, u.first_name FROM transactions t JOIN users u ON u.user_id=t.user_id WHERE t.type='withdraw' ORDER BY t.id DESC").fetchall()
        if not rows:
            await send_message_safe(q.bot, q.message.chat.id, "Нет данных для выгрузки.")
            return
        lines = ["ОТЧЕТ: WITHDRAW REQUESTS", f"Дата выгрузки: {db.now_str()}", f"Всего заявок: {len(rows)}", "", "=" * 50]
        for r in rows:
            meta = parse_meta(r["meta"])
            lines.append(
                f"ID заявки: {r['id']}\nПользователь: {r['user_id']}\nUsername: @{r['username'] or '—'}\nИмя: {r['first_name'] or '—'}\nСумма: {r['amount']:.2f} USDT\nАдрес: {meta.get('address','—')}\nСтатус: {r['status']}\nДата создания: {r['created_at']}\nДата завершения: {r['completed_at'] or '—'}\n" + "-" * 40
            )
        path = _write_export_file(f"withdraws_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.txt", "\n\n".join(lines))
        await send_document_safe(q.bot, q.message.chat.id, FSInputFile(str(path)))
        path.unlink(missing_ok=True)
        return

    if q.data == "noop":
        return

    if q.data in {"back_main", "wallet_back", "go_main_menu"}:
        state.clear(); await delete_message_safe(q.bot, q.message.chat.id, q.message.message_id); await send_main_menu(q.bot, q.message.chat.id); return

    if q.data == "menu_info":
        txt = "ℹ️ Информация\n\nМы инвестиционный проект, который позволяет:\n• пополнять баланс;\n• использовать стейкинг;\n• выводить средства;\n• зарабатывать на партнерской программе.\n\nПланы стейкинга:\n• Дневной — 1 день, +1%\n• Недельный — 7 дней, +5%\n• Месячный — 10 дней, +10%\n\nМинимальные суммы:\n" + f"• Пополнение: {SETTINGS.min_deposit_usdt:g} USDT\n• Стейкинг: {SETTINGS.min_stake_usdt:g} USDT\n• Вывод: {SETTINGS.min_withdraw_usdt:g} USDT\n\nПоддержка: @{SETTINGS.support_username}"
        await open_section(q, txt, kb([[back_btn()]]), SETTINGS.info_banner_path); return
    if q.data == "menu_wallet":
        u = db.get_user(uid)
        txt = f"💰 Ваш кошелек\n\n💵 Доступный баланс: {u['balance']:.2f} USDT\n🔒 В стейкинге: {u['staked_balance']:.2f} USDT\n📊 Активных стейков: {db.get_active_stakes_count(uid)}\n\nВыберите действие:"
        await open_section(q, txt, wallet_kb(), SETTINGS.wallet_banner_path); return
    if q.data == "wallet_deposit":
        await open_section(q, "💼 Пополнение баланса\n\nВыберите способ пополнения:", kb([[styled_button("Crypto Bot", callback_data="deposit_crypto")], [styled_button("Telegram Stars", callback_data="deposit_stars")], [back_btn("menu_wallet")]])); return
    if q.data in {"deposit_crypto", "deposit_stars"}:
        state["state"] = "await_deposit"; state["deposit_method"] = "cryptobot" if q.data == "deposit_crypto" else "stars"
        await open_section(q, f"Введите сумму пополнения (минимум {SETTINGS.min_deposit_usdt:g} USDT):", kb([[back_btn("menu_wallet")]])); return
    if q.data == "wallet_withdraw":
        state["state"] = "await_withdraw"; u = db.get_user(uid)
        await open_section(q, f"📤 Вывод средств\n\n💰 Ваш баланс: {u['balance']:.2f} USDT\nМинимальная сумма вывода: {SETTINGS.min_withdraw_usdt:g} USDT\n\nВведите сумму для вывода:", kb([[back_btn("menu_wallet")]])); return
    if q.data == "wallet_stake":
        await open_section(q, "📊 Стейкинг\n\n📅 Дневной план\n• Срок: 1 день\n• Доход: +1%\n\n📅 Недельный план\n• Срок: 7 дней\n• Доход: +5%\n\n📈 Месячный план\n• Срок: 10 дней\n• Доход: +10%\n\nВыберите план:", kb([[styled_button("Дневной", callback_data="staking_daily"), styled_button("Недельный", callback_data="staking_weekly")], [styled_button("Месячный", callback_data="staking_monthly"), styled_button("Мои стейки", callback_data="staking_my")], [back_btn("menu_wallet")]])); return
    if q.data in {"staking_daily", "staking_weekly", "staking_monthly"}:
        plan = q.data.split("_")[1]; state["state"] = "await_stake"; state["stake_plan"] = plan; p = SETTINGS.plans[plan]
        await open_section(q, f"📊 {p.title} план\nПериод: {p.days} дн.\nДоход: +{p.percent}%\n\nВведите сумму:", kb([[back_btn("wallet_stake")]])); return
    if q.data == "staking_my":
        rows = db.list_active_stakes(uid)
        txt = "📭 У вас пока нет активных стейков." if not rows else "📊 Ваши активные стейки:\n\n" + "\n\n".join([f"• {PLAN_TRANSLATIONS.get(s['plan'], s['plan'])}\n  Сумма: {s['amount']:.2f} USDT\n  Доход: {s['profit']:.2f} USDT\n  Завершится: {s['end_time']}" for s in rows])
        await open_section(q, txt, kb([[back_btn("wallet_stake")]])); return
    if q.data == "wallet_history":
        txs = db.list_recent_transactions(uid, 10)
        txt = "📜 История пуста." if not txs else "📜 Последние транзакции:\n\n" + "\n\n".join([f"{status_emoji(t['status'])} {TX_TRANSLATIONS.get(t['type'], t['type'].title())}: {t['amount']:.2f} {t['currency']}\n{t['created_at']}" for t in txs])
        await open_section(q, txt, kb([[back_btn("menu_wallet")]])); return
    if q.data == "menu_referrals":
        u = db.get_user(uid)
        with db.conn() as c:
            refs = c.execute("SELECT COUNT(*) c FROM users WHERE referrer_id=?", (uid,)).fetchone()["c"]
        link = referral_link(u["referral_code"])
        txt = f"👥 Реферальная программа\n\n🎁 Получайте {SETTINGS.referral_percent:g}% от депозитов ваших рефералов!\n\n📊 Ваша статистика:\n• Рефералов: {refs}\n• Заработано: {u['referral_earned']:.2f} USDT\n\n🔗 Ваша реферальная ссылка:\n{link}\n\nДелитесь ссылкой с друзьями и зарабатывайте!"
        await open_section(q, txt, kb([[copy_button("Скопировать", link)], [back_btn()]]), SETTINGS.referrals_banner_path); return


@router.message(F.text)
async def amount_input(message: Message) -> None:
    uid = message.from_user.id
    if db.is_user_blocked(uid):
        return
    state = user_states.setdefault(uid, {})
    step = state.get("state")
    if not step:
        return

    if step == "waiting_user_search_query" and db.is_admin(uid):
        query = message.text.strip()
        user = db.get_user(int(query)) if query.isdigit() else db.get_user_by_username(query.lstrip("@"))
        if not user:
            await message.answer("Пользователь не найден.")
            return
        state.clear(); state["last_found_user"] = user["user_id"]
        await message.answer(user_card(user), reply_markup=user_card_kb(uid, user["user_id"], bool(user["is_blocked"])))
        return

    if step == "waiting_new_admin_id" and db.is_main_admin(uid):
        raw = message.text.strip()
        if not raw.isdigit():
            await message.answer("Введите корректный числовой TG ID.")
            return
        new_admin_id = int(raw)
        if new_admin_id == SETTINGS.main_admin_id:
            await message.answer("Нельзя добавить MAIN_ADMIN_ID как обычного админа.")
            return
        if db.is_admin(new_admin_id):
            await message.answer("Пользователь уже админ.")
            return
        with db.conn() as c:
            c.execute(
                "INSERT OR IGNORE INTO admins(user_id, role, added_by, created_at) VALUES(?,?,?,?)",
                (new_admin_id, "admin", uid, db.now_str()),
            )
        db.log_admin(uid, "add_admin", target_type="admin", target_id=new_admin_id)
        state.clear()
        await message.answer(f"✅ Админ {new_admin_id} добавлен.")
        return

    if step == "waiting_remove_admin_id" and db.is_main_admin(uid):
        raw = message.text.strip()
        if not raw.isdigit():
            await message.answer("Введите корректный числовой TG ID.")
            return
        remove_admin_id = int(raw)
        if remove_admin_id == SETTINGS.main_admin_id:
            await message.answer("Нельзя удалить MAIN_ADMIN_ID.")
            return
        if remove_admin_id in SETTINGS.admin_ids:
            await message.answer("Этот админ задан через .env. Удалить его можно только из ADMIN_IDS.")
            return
        with db.conn() as c:
            cur = c.execute("DELETE FROM admins WHERE user_id=?", (remove_admin_id,))
            if cur.rowcount == 0:
                await message.answer("Админ не найден.")
                return
        db.log_admin(uid, "remove_admin", target_type="admin", target_id=remove_admin_id)
        state.clear()
        await message.answer(f"✅ Админ {remove_admin_id} удален.")
        return
    if step == "waiting_broadcast_message" and db.is_main_admin(uid):
        audience = state.get("broadcast_audience", "all")
        recipients = broadcast_audience_ids(audience)
        state["broadcast_recipients"] = recipients
        state["state"] = "waiting_broadcast_confirm"
        state["broadcast_text"] = message.text
        state["broadcast_photo"] = None
        await message.answer("Предпросмотр:\n\n" + message.text)
        await message.answer(
            f"Аудитория: {audience}\nПолучателей: {len(recipients)}\n\nОтправить рассылку?",
            reply_markup=kb([[styled_button("✅ Отправить", callback_data="admin_broadcast_confirm"), styled_button("❌ Отмена", callback_data="admin_broadcast_cancel")]]),
        )
        db.log_admin(uid, "broadcast_confirm_prompt", details=f"audience={audience};count={len(recipients)}")
        return

    if step in {"waiting_credit_amount", "waiting_debit_amount"} and db.is_main_admin(uid):
        try:
            amount = float(message.text.replace(",", "."))
            if amount <= 0:
                raise ValueError
        except ValueError:
            await message.answer("Введите корректную сумму больше 0.")
            return
        target = int(state["target_user"]); user = db.get_user(target)
        if step == "waiting_debit_amount" and amount > user["balance"]:
            await message.answer("Сумма больше доступного баланса пользователя.")
            return
        state["pending_amount"] = amount
        action = "admin_credit_confirm" if step == "waiting_credit_amount" else "admin_debit_confirm"
        title = "➕ Начисление баланса" if step == "waiting_credit_amount" else "➖ Списание баланса"
        after = user["balance"] + amount if step == "waiting_credit_amount" else user["balance"] - amount
        await message.answer(f"{title}\n\nПользователь: {target} / @{user['username'] or '—'}\nСумма: {amount:.2f} USDT\n\nБаланс сейчас: {user['balance']:.2f} USDT\nБаланс после: {after:.2f} USDT\n\nПодтвердить?", reply_markup=kb([[styled_button("✅ Подтвердить", callback_data=f"{action}:{target}"), styled_button("❌ Отмена", callback_data="admin_back")]]))
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
        admin_ids = db.get_all_admin_ids() if SETTINGS.withdraw_notify_all_admins else [SETTINGS.main_admin_id]
        for aid in admin_ids:
            if not aid:
                continue
            await send_message_safe(message.bot, aid, f"💸 Новая заявка на вывод\n\nПользователь: {uid} / @{message.from_user.username or '—'}\nИмя: {message.from_user.first_name or '—'}\nСумма: {amount:.2f} USDT\nАдрес: —\nДата: {db.now_str()}\n\nОткройте раздел “Заявки на вывод” в админке.", reply_markup=kb([[styled_button("💸 Открыть заявки", callback_data="admin_withdraws_pending")]]))
    elif step == "await_stake":
        if amount < SETTINGS.min_stake_usdt:
            await message.answer(f"Минимальная сумма стейкинга: {SETTINGS.min_stake_usdt:g} USDT")
            return
        if amount > user["balance"]:
            await message.answer("Недостаточно средств.")
            return
        plan = SETTINGS.plans[state["stake_plan"]]
        profit = round(amount * plan.percent / 100, 2)
        end = (datetime.now(UTC) + timedelta(days=plan.days)).strftime("%Y-%m-%d %H:%M:%S")
        db.update_balance(uid, delta_balance=-amount, delta_staked=amount)
        db.create_stake(uid, plan.key, amount, plan.percent, profit, round(amount + profit, 2), end)
        db.add_transaction(uid, "stake", amount, status="completed", completed=True, meta={"plan": plan.key})
        state.clear()
        await message.answer(f"✅ Подтверждение стейка\n\nСумма: {amount:.2f} USDT\nДоход: +{profit:.2f} USDT\nДата окончания: {end}", reply_markup=kb([[styled_button("🏠 Главное меню", callback_data="go_main_menu")]]))


@router.message(F.photo)
async def broadcast_photo_input(message: Message) -> None:
    uid = message.from_user.id
    if db.is_user_blocked(uid):
        return
    state = user_states.setdefault(uid, {})
    if state.get("state") != "waiting_broadcast_message" or not db.is_main_admin(uid):
        return
    audience = state.get("broadcast_audience", "all")
    recipients = broadcast_audience_ids(audience)
    state["broadcast_recipients"] = recipients
    state["state"] = "waiting_broadcast_confirm"
    state["broadcast_photo"] = message.photo[-1].file_id
    state["broadcast_text"] = message.caption or ""
    await message.answer_photo(photo=state["broadcast_photo"], caption=state["broadcast_text"] or "(без подписи)")
    await message.answer(
        f"Аудитория: {audience}\nПолучателей: {len(recipients)}\n\nОтправить рассылку?",
        reply_markup=kb([[styled_button("✅ Отправить", callback_data="admin_broadcast_confirm"), styled_button("❌ Отмена", callback_data="admin_broadcast_cancel")]]),
    )
    db.log_admin(uid, "broadcast_confirm_prompt", details=f"audience={audience};count={len(recipients)};photo=1")


async def main() -> None:
    global BOT_USERNAME_RUNTIME
    print("Aiogram version:", aiogram.__version__)
    if not SETTINGS.main_admin_id:
        print("[ERROR] MAIN_ADMIN_ID не указан в .env")
    db.init_db()
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(db.process_finished_stakes, "interval", minutes=1)
    scheduler.start()

    bot = Bot(token=SETTINGS.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    me = await bot.get_me()
    BOT_USERNAME_RUNTIME = SETTINGS.bot_username or me.username or ""

    dp = Dispatcher()
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
