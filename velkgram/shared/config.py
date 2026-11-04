"""Environment-backed settings."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


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

    def __repr__(self) -> str:
        def mask(value: str | None) -> str:
            return "None" if value is None else "'***'"

        return (
            f"Settings(tg_api_id={self.tg_api_id!r}, tg_api_hash={mask(self.tg_api_hash)}, "
            f"tg_session={mask(self.tg_session)}, db_path={self.db_path!r}, "
            f"notifier={self.notifier!r}, web_password_hash={mask(self.web_password_hash)}, "
            f"web_secret_key={mask(self.web_secret_key)}, log_level={self.log_level!r})"
        )


def load_settings(env: Mapping[str, str]) -> Settings:
    notifier = env.get("NOTIFIER", "log")
    if notifier != "log":
        raise ValueError(f"unknown NOTIFIER: {notifier}")
    api_id = env.get("TG_API_ID")
    return Settings(
        tg_api_id=int(api_id) if api_id else None,
        tg_api_hash=env.get("TG_API_HASH") or None,
        tg_session=env.get("TG_SESSION") or None,
        db_path=Path(env.get("DB_PATH", "./data/velkgram.db")),
        notifier=notifier,
        web_password_hash=env.get("WEB_PASSWORD_HASH") or None,
        web_secret_key=env.get("WEB_SECRET_KEY") or None,
        log_level=env.get("LOG_LEVEL", "INFO"),
    )
