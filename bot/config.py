from dataclasses import dataclass
import os
from dotenv import load_dotenv

load_dotenv()


def _parse_admin_ids(raw: str) -> tuple[int, ...]:
    ids = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        if part.isdigit():
            ids.append(int(part))
    return tuple(dict.fromkeys(ids))


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
    main_banner_path: str = os.getenv("MAIN_BANNER_PATH", "").strip()
    wallet_banner_path: str = os.getenv("WALLET_BANNER_PATH", "").strip()
    info_banner_path: str = os.getenv("INFO_BANNER_PATH", "").strip()
    referrals_banner_path: str = os.getenv("REFERRALS_BANNER_PATH", "").strip()

    min_deposit_usdt: float = float(os.getenv("MIN_DEPOSIT_USDT", "15"))
    min_stake_usdt: float = float(os.getenv("MIN_STAKE_USDT", "15"))
    min_withdraw_usdt: float = float(os.getenv("MIN_WITHDRAW_USDT", "20"))
    referral_percent: float = float(os.getenv("REFERRAL_PERCENT", "7"))

    main_admin_id: int = int(os.getenv("MAIN_ADMIN_ID", "0") or "0")
    admin_ids: tuple[int, ...] = _parse_admin_ids(os.getenv("ADMIN_IDS", ""))
    admin_can_process_withdraws: bool = os.getenv("ADMIN_CAN_PROCESS_WITHDRAWS", "false").lower() == "true"
    withdraw_notify_all_admins: bool = os.getenv("WITHDRAW_NOTIFY_ALL_ADMINS", "false").lower() == "true"

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
