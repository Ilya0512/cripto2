import json
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path("bot.db")


def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def now_str():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


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
                created_at TEXT NOT NULL
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
            CREATE INDEX IF NOT EXISTS idx_transactions_user ON transactions(user_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_stakes_active ON stakes(status, end_time);
            """
        )
        _migrate_schema(c)


def _table_columns(c, table_name):
    return {row["name"] for row in c.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _migrate_schema(c):
    tx_columns = _table_columns(c, "transactions")
    if "id" not in tx_columns:
        old_tx_columns = tx_columns
        c.execute("ALTER TABLE transactions RENAME TO transactions_old")
        c.execute(
            """
            CREATE TABLE transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                type TEXT NOT NULL,
                amount REAL NOT NULL,
                currency TEXT DEFAULT 'USDT',
                status TEXT NOT NULL,
                meta TEXT NULL,
                created_at TEXT NOT NULL,
                completed_at TEXT NULL
            )
            """
        )
        currency_expr = "currency" if "currency" in old_tx_columns else "'USDT'"
        meta_expr = "meta" if "meta" in old_tx_columns else "NULL"
        completed_at_expr = "completed_at" if "completed_at" in old_tx_columns else "NULL"
        c.execute(
            f"""
            INSERT INTO transactions(user_id,type,amount,currency,status,meta,created_at,completed_at)
            SELECT user_id, type, amount, {currency_expr}, status, {meta_expr}, created_at, {completed_at_expr}
            FROM transactions_old
            """
        )
        c.execute("DROP TABLE transactions_old")
        tx_columns = _table_columns(c, "transactions")

    if "currency" not in tx_columns:
        c.execute("ALTER TABLE transactions ADD COLUMN currency TEXT DEFAULT 'USDT'")
    if "meta" not in tx_columns:
        c.execute("ALTER TABLE transactions ADD COLUMN meta TEXT NULL")
    if "completed_at" not in tx_columns:
        c.execute("ALTER TABLE transactions ADD COLUMN completed_at TEXT NULL")

    user_columns = _table_columns(c, "users")
    if "referral_earned" not in user_columns:
        c.execute("ALTER TABLE users ADD COLUMN referral_earned REAL DEFAULT 0")

    stakes_columns = _table_columns(c, "stakes")
    if "percent" not in stakes_columns:
        c.execute("ALTER TABLE stakes ADD COLUMN percent REAL NOT NULL DEFAULT 0")
    if "profit" not in stakes_columns:
        c.execute("ALTER TABLE stakes ADD COLUMN profit REAL NOT NULL DEFAULT 0")
    if "total_payout" not in stakes_columns:
        c.execute("ALTER TABLE stakes ADD COLUMN total_payout REAL NOT NULL DEFAULT 0")
    if "completed_at" not in stakes_columns:
        c.execute("ALTER TABLE stakes ADD COLUMN completed_at TEXT NULL")


def ensure_user(tg_user, referral_code=None):
    with conn() as c:
        row = c.execute("SELECT * FROM users WHERE user_id=?", (tg_user.id,)).fetchone()
        if row:
            if not row["referral_code"]:
                c.execute("UPDATE users SET referral_code=? WHERE user_id=?", (f"ref{tg_user.id}", tg_user.id))
            if row["referrer_id"] is None and referral_code:
                ref = get_user_by_referral_code(referral_code)
                if ref and ref["user_id"] != tg_user.id:
                    c.execute("UPDATE users SET referrer_id=? WHERE user_id=?", (ref["user_id"], tg_user.id))
            return
        referrer_id = None
        if referral_code:
            ref = get_user_by_referral_code(referral_code)
            if ref and ref["user_id"] != tg_user.id:
                referrer_id = ref["user_id"]
        c.execute(
            "INSERT INTO users(user_id,username,first_name,referral_code,referrer_id,created_at) VALUES(?,?,?,?,?,?)",
            (tg_user.id, tg_user.username, tg_user.first_name, f"ref{tg_user.id}", referrer_id, now_str()),
        )


def get_user(user_id):
    with conn() as c:
        return c.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()


def get_user_by_referral_code(code):
    with conn() as c:
        return c.execute("SELECT * FROM users WHERE referral_code=?", (code,)).fetchone()


def update_balance(user_id, delta_balance=0, delta_staked=0):
    with conn() as c:
        c.execute("UPDATE users SET balance=balance+?, staked_balance=staked_balance+? WHERE user_id=?", (delta_balance, delta_staked, user_id))


def add_transaction(user_id, tx_type, amount, status="pending", currency="USDT", meta=None, completed=False):
    with conn() as c:
        c.execute(
            "INSERT INTO transactions(user_id,type,amount,currency,status,meta,created_at,completed_at) VALUES(?,?,?,?,?,?,?,?)",
            (user_id, tx_type, amount, currency, status, json.dumps(meta) if meta else None, now_str(), now_str() if completed else None),
        )
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
        c.execute(
            "INSERT INTO stakes(user_id,plan,amount,percent,profit,total_payout,status,start_time,end_time) VALUES(?,?,?,?,?,?,?,?,?)",
            (user_id, plan, amount, percent, profit, total_payout, "active", now_str(), end_time),
        )


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
