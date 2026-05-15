import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path("bot.db")


def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                balance REAL DEFAULT 0,
                staked_balance REAL DEFAULT 0,
                referral_code TEXT UNIQUE,
                referrer_id INTEGER
            );
            CREATE TABLE IF NOT EXISTS transactions (
                tx_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                type TEXT,
                amount REAL,
                currency TEXT,
                status TEXT,
                created_at TEXT,
                completed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS stakes (
                stake_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                plan TEXT,
                amount REAL,
                income REAL,
                start_time TEXT,
                end_time TEXT,
                status TEXT
            );
            """
        )


def now():
    return datetime.utcnow().isoformat(sep=" ", timespec="seconds")


def ensure_user(user_id: int, referrer_id=None):
    code = f"ref{user_id}"
    with conn() as c:
        c.execute("INSERT OR IGNORE INTO users(user_id, referral_code, referrer_id) VALUES(?,?,?)", (user_id, code, referrer_id))


def get_user(user_id: int):
    with conn() as c:
        return c.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()


def add_transaction(user_id, tx_type, amount, currency="USDT", status="successful", completed=True):
    with conn() as c:
        c.execute(
            "INSERT INTO transactions(user_id,type,amount,currency,status,created_at,completed_at) VALUES(?,?,?,?,?,?,?)",
            (user_id, tx_type, amount, currency, status, now(), now() if completed else None),
        )


def update_balance(user_id, delta_balance=0.0, delta_staked=0.0):
    with conn() as c:
        c.execute("UPDATE users SET balance=balance+?, staked_balance=staked_balance+? WHERE user_id=?", (delta_balance, delta_staked, user_id))


def create_stake(user_id, plan, amount, income, end_time):
    with conn() as c:
        c.execute(
            "INSERT INTO stakes(user_id,plan,amount,income,start_time,end_time,status) VALUES(?,?,?,?,?,?,?)",
            (user_id, plan, amount, income, now(), end_time, "active"),
        )


def get_active_stakes_count(user_id):
    with conn() as c:
        r = c.execute("SELECT COUNT(*) c FROM stakes WHERE user_id=? AND status='active'", (user_id,)).fetchone()
        return r["c"]


def list_recent_transactions(user_id, limit=10):
    with conn() as c:
        return c.execute("SELECT * FROM transactions WHERE user_id=? ORDER BY tx_id DESC LIMIT ?", (user_id, limit)).fetchall()


def get_ref_stats(user_id):
    with conn() as c:
        refs = c.execute("SELECT COUNT(*) c FROM users WHERE referrer_id=?", (user_id,)).fetchone()["c"]
        earned = c.execute("SELECT COALESCE(SUM(amount),0) s FROM transactions WHERE user_id=? AND type='ref_bonus'", (user_id,)).fetchone()["s"]
        return refs, earned


def process_finished_stakes():
    with conn() as c:
        rows = c.execute("SELECT * FROM stakes WHERE status='active' AND end_time<=?", (now(),)).fetchall()
        for s in rows:
            payout = s["amount"] + s["income"]
            c.execute("UPDATE stakes SET status='completed' WHERE stake_id=?", (s["stake_id"],))
            c.execute("UPDATE users SET balance=balance+?, staked_balance=staked_balance-? WHERE user_id=?", (payout, s["amount"], s["user_id"]))
            c.execute("INSERT INTO transactions(user_id,type,amount,currency,status,created_at,completed_at) VALUES(?,?,?,?,?,?,?)",
                      (s["user_id"], "stake_profit", s["income"], "USDT", "successful", now(), now()))
