"""Environment-backed settings."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True)
class Settings:
    tg_api_id: int | None = None
    tg_api_hash: str | None = None
    tg_session: str | None = None
    db_path: Path = Path("./data/velkgram.db")
    notifier: Literal["log"] = "log"
    web_password_hash: str | None = None
    web_secret_key: str | None = None
    log_level: str = "INFO"
    retention_days: int = 90
    app_timezone: ZoneInfo = field(default_factory=lambda: ZoneInfo("America/Sao_Paulo"))

    def __repr__(self) -> str:
        def mask(value: str | None) -> str:
            return "None" if value is None else "'***'"

        return (
            f"Settings(tg_api_id={self.tg_api_id!r}, tg_api_hash={mask(self.tg_api_hash)}, "
            f"tg_session={mask(self.tg_session)}, db_path={self.db_path!r}, "
            f"notifier={self.notifier!r}, web_password_hash={mask(self.web_password_hash)}, "
            f"web_secret_key={mask(self.web_secret_key)}, log_level={self.log_level!r}, "
            f"retention_days={self.retention_days}, app_timezone={self.app_timezone.key!r})"
        )


def _value(env: Mapping[str, str], key: str, default: str) -> str:
    """Empty or whitespace-only values count as unset."""
    return (env.get(key) or "").strip() or default


def _retention_days(env: Mapping[str, str]) -> int:
    raw = _value(env, "RETENTION_DAYS", "90")
    try:
        days = int(raw)
    except ValueError:
        raise ValueError(f"RETENTION_DAYS must be an integer: {raw}") from None
    if days < 30:
        raise ValueError(f"RETENTION_DAYS must be at least 30: {days}")
    return days


def _app_timezone(env: Mapping[str, str]) -> ZoneInfo:
    name = _value(env, "APP_TIMEZONE", "America/Sao_Paulo")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"unknown APP_TIMEZONE: {name}") from exc


def load_settings(env: Mapping[str, str]) -> Settings:
    notifier = _value(env, "NOTIFIER", "log")
    if notifier != "log":
        raise ValueError(f"unknown NOTIFIER: {notifier}")
    api_id = env.get("TG_API_ID")
    return Settings(
        tg_api_id=int(api_id) if api_id else None,
        tg_api_hash=env.get("TG_API_HASH") or None,
        tg_session=env.get("TG_SESSION") or None,
        db_path=Path(_value(env, "DB_PATH", "./data/velkgram.db")),
        notifier=notifier,
        web_password_hash=env.get("WEB_PASSWORD_HASH") or None,
        web_secret_key=env.get("WEB_SECRET_KEY") or None,
        log_level=_value(env, "LOG_LEVEL", "INFO"),
        retention_days=_retention_days(env),
        app_timezone=_app_timezone(env),
    )
