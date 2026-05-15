from dataclasses import dataclass, field
import os
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class StakingPlan:
    key: str
    title: str
    days: int
    percent: float

@dataclass(frozen=True)
class Settings:
    project_name: str = os.getenv("PROJECT_NAME", "Crypto Invest Bot")
    bot_token: str = os.getenv("BOT_TOKEN", "")
    support_username: str = os.getenv("SUPPORT_USERNAME", "chromkey")
    support_chat_url: str = os.getenv("SUPPORT_CHAT_URL", "https://t.me/chromkey")
    base_ref_url: str = os.getenv("BASE_REF_URL", "https://t.me/your_bot_username?start=")

    min_deposit_usdt: float = float(os.getenv("MIN_DEPOSIT_USDT", "0.1"))
    min_stake_usdt: float = float(os.getenv("MIN_STAKE_USDT", "10"))
    min_withdraw_usdt: float = float(os.getenv("MIN_WITHDRAW_USDT", "5"))
    referral_percent: float = float(os.getenv("REFERRAL_PERCENT", "5"))

    plans: dict = field(default_factory=lambda: {
        "daily": StakingPlan("daily", os.getenv("PLAN_DAILY_TITLE", "Дневной"), int(os.getenv("PLAN_DAILY_DAYS", "1")), float(os.getenv("PLAN_DAILY_PERCENT", "1"))),
        "weekly": StakingPlan("weekly", os.getenv("PLAN_WEEKLY_TITLE", "Недельный"), int(os.getenv("PLAN_WEEKLY_DAYS", "7")), float(os.getenv("PLAN_WEEKLY_PERCENT", "5"))),
        "monthly": StakingPlan("monthly", os.getenv("PLAN_MONTHLY_TITLE", "Месячный"), int(os.getenv("PLAN_MONTHLY_DAYS", "10")), float(os.getenv("PLAN_MONTHLY_PERCENT", "10"))),
    })

SETTINGS = Settings()
