import json
import sqlite3
from datetime import datetime
from pathlib import Path

from bot.config import SETTINGS

DB_PATH = Path("bot.db")


def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def now_str():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _table_columns(c, table_name):
    return {row["name"] for row in c.execute(f"PRAGMA table_info({table_name})").fetchall()}


def init_db():
    with conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                balance REAL DEFAULT 0,
                staked_balance REAL DEFAULT 0,
                referral_code TEXT UNIQUE,
                referrer_id INTEGER NULL,
                referral_earned REAL DEFAULT 0,
                created_at TEXT NOT NULL,
                is_blocked INTEGER DEFAULT 0,
                blocked_at TEXT NULL,
                blocked_by INTEGER NULL
            );
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                type TEXT NOT NULL,
                amount REAL NOT NULL,
                currency TEXT DEFAULT 'USDT',
                status TEXT NOT NULL,
                meta TEXT NULL,
                created_at TEXT NOT NULL,
                completed_at TEXT NULL
            );
            CREATE TABLE IF NOT EXISTS stakes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                plan TEXT NOT NULL,
                amount REAL NOT NULL,
                percent REAL NOT NULL,
                profit REAL NOT NULL,
                total_payout REAL NOT NULL,
                status TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                completed_at TEXT NULL
            );
            CREATE TABLE IF NOT EXISTS admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE NOT NULL,
                role TEXT NOT NULL DEFAULT 'admin',
                added_by INTEGER NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS admin_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                target_type TEXT NULL,
                target_id TEXT NULL,
                details TEXT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        user_columns = [
            ("username", "TEXT"),
            ("first_name", "TEXT"),
            ("balance", "REAL DEFAULT 0"),
            ("staked_balance", "REAL DEFAULT 0"),
            ("referral_code", "TEXT"),
            ("referrer_id", "INTEGER NULL"),
            ("referral_earned", "REAL DEFAULT 0"),
            ("created_at", "TEXT"),
            ("is_blocked", "INTEGER DEFAULT 0"),
            ("blocked_at", "TEXT NULL"),
            ("blocked_by", "INTEGER NULL"),
        ]
        for col, typ in user_columns:
            if col not in _table_columns(c, "users"):
                c.execute(f"ALTER TABLE users ADD COLUMN {col} {typ}")
        sync_admins_from_env()


def sync_admins_from_env():
    with conn() as c:
        env_admins = set(SETTINGS.admin_ids)
        env_admins.discard(SETTINGS.main_admin_id)
        for uid in env_admins:
            c.execute("INSERT OR IGNORE INTO admins(user_id, role, added_by, created_at) VALUES(?,?,?,?)", (uid, "admin", SETTINGS.main_admin_id or None, now_str()))


def is_main_admin(user_id: int) -> bool:
    return bool(SETTINGS.main_admin_id and user_id == SETTINGS.main_admin_id)


def is_admin(user_id: int) -> bool:
    if is_main_admin(user_id):
        return True
    if user_id in SETTINGS.admin_ids:
        return True
    with conn() as c:
        row = c.execute("SELECT 1 FROM admins WHERE user_id=?", (user_id,)).fetchone()
    return row is not None


def is_user_blocked(user_id: int) -> bool:
    if is_admin(user_id):
        return False
    with conn() as c:
        row = c.execute("SELECT is_blocked FROM users WHERE user_id=?", (user_id,)).fetchone()
    return bool(row and row["is_blocked"])


def log_admin(admin_id: int, action: str, target_type=None, target_id=None, details=None):
    with conn() as c:
        c.execute("INSERT INTO admin_logs(admin_id,action,target_type,target_id,details,created_at) VALUES(?,?,?,?,?,?)", (admin_id, action, target_type, str(target_id) if target_id is not None else None, details, now_str()))

# existing funcs below

def ensure_user(tg_user, referral_code=None):
    with conn() as c:
        row = c.execute("SELECT * FROM users WHERE user_id=?", (tg_user.id,)).fetchone()
        if row:
            c.execute("UPDATE users SET username=?, first_name=? WHERE user_id=?", (tg_user.username, tg_user.first_name, tg_user.id))
            return
        referrer_id = None
        if referral_code:
            ref = get_user_by_referral_code(referral_code)
            if ref and ref["user_id"] != tg_user.id:
                referrer_id = ref["user_id"]
        c.execute("INSERT INTO users(user_id,username,first_name,referral_code,referrer_id,created_at) VALUES(?,?,?,?,?,?)", (tg_user.id, tg_user.username, tg_user.first_name, f"ref{tg_user.id}", referrer_id, now_str()))


def get_user(user_id):
    with conn() as c:
        return c.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()

def get_user_by_username(username: str):
    with conn() as c:
        return c.execute("SELECT * FROM users WHERE lower(username)=lower(?)", (username.lstrip("@"),)).fetchone()

def get_user_by_referral_code(code):
    with conn() as c:
        return c.execute("SELECT * FROM users WHERE referral_code=?", (code,)).fetchone()

def update_balance(user_id, delta_balance=0, delta_staked=0):
    with conn() as c:
        c.execute("UPDATE users SET balance=balance+?, staked_balance=staked_balance+? WHERE user_id=?", (delta_balance, delta_staked, user_id))

def add_transaction(user_id, tx_type, amount, status="pending", currency="USDT", meta=None, completed=False):
    with conn() as c:
        c.execute("INSERT INTO transactions(user_id,type,amount,currency,status,meta,created_at,completed_at) VALUES(?,?,?,?,?,?,?,?)", (user_id, tx_type, amount, currency, status, json.dumps(meta, ensure_ascii=False) if meta else None, now_str(), now_str() if completed else None))
        return c.execute("SELECT last_insert_rowid() lid").fetchone()["lid"]

def complete_transaction(tx_id):
    with conn() as c:
        c.execute("UPDATE transactions SET status='completed', completed_at=? WHERE id=?", (now_str(), tx_id))

def list_recent_transactions(user_id, limit=10):
    with conn() as c:
        return c.execute("SELECT * FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit)).fetchall()

def get_active_stakes_count(user_id):
    with conn() as c:
        return c.execute("SELECT COUNT(*) c FROM stakes WHERE user_id=? AND status='active'", (user_id,)).fetchone()["c"]

def create_stake(user_id, plan, amount, percent, profit, total_payout, end_time):
    with conn() as c:
        c.execute("INSERT INTO stakes(user_id,plan,amount,percent,profit,total_payout,status,start_time,end_time) VALUES(?,?,?,?,?,?,?,?,?)", (user_id, plan, amount, percent, profit, total_payout, "active", now_str(), end_time))

def list_active_stakes(user_id):
    with conn() as c:
        return c.execute("SELECT * FROM stakes WHERE user_id=? AND status='active' ORDER BY end_time", (user_id,)).fetchall()

def process_finished_stakes():
    with conn() as c:
        rows = c.execute("SELECT * FROM stakes WHERE status='active' AND end_time<=?", (now_str(),)).fetchall()
        for s in rows:
            c.execute("UPDATE stakes SET status='completed', completed_at=? WHERE id=?", (now_str(), s["id"]))
            c.execute("UPDATE users SET balance=balance+?, staked_balance=staked_balance-? WHERE user_id=?", (s["total_payout"], s["amount"], s["user_id"]))
            add_transaction(s["user_id"], "stake_profit", s["profit"], status="completed", completed=True, meta={"stake_id": s["id"]})

def apply_referral_bonus_if_needed(user_id, deposit_amount, referral_percent):
    with conn() as c:
        user = c.execute("SELECT referrer_id FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not user or not user["referrer_id"]:
            return
        bonus = round(deposit_amount * referral_percent / 100, 2)
        c.execute("UPDATE users SET balance=balance+?, referral_earned=referral_earned+? WHERE user_id=?", (bonus, bonus, user["referrer_id"]))
        add_transaction(user["referrer_id"], "referral_bonus", bonus, status="completed", completed=True, meta={"from_user": user_id})


def get_all_admin_ids():
    ids = set()
    if SETTINGS.main_admin_id:
        ids.add(SETTINGS.main_admin_id)
    ids.update(SETTINGS.admin_ids)
    with conn() as c:
        rows = c.execute("SELECT user_id FROM admins").fetchall()
        ids.update([r["user_id"] for r in rows])
    return sorted(ids)
