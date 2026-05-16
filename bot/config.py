from dataclasses import dataclass
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
    bot_token: str = os.getenv("BOT_TOKEN", "")
    bot_username: str = os.getenv("BOT_USERNAME", "").strip()
    support_username: str = os.getenv("SUPPORT_USERNAME", "").strip().lstrip("@")
    banner_path: str = os.getenv("BANNER_PATH", "")
    cryptobot_token: str = os.getenv("CRYPTOBOT_TOKEN", "")

    min_deposit_usdt: float = float(os.getenv("MIN_DEPOSIT_USDT", "15"))
    min_stake_usdt: float = float(os.getenv("MIN_STAKE_USDT", "15"))
    min_withdraw_usdt: float = float(os.getenv("MIN_WITHDRAW_USDT", "20"))
    referral_percent: float = float(os.getenv("REFERRAL_PERCENT", "7"))

    plans: dict = None

    def __post_init__(self):
        object.__setattr__(
            self,
            "plans",
            {
                "daily": StakingPlan("daily", "Дневной", 1, 1),
                "weekly": StakingPlan("weekly", "Недельный", 7, 5),
                "monthly": StakingPlan("monthly", "Месячный", 10, 10),
            },
        )


SETTINGS = Settings()
