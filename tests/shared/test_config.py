from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from velkgram.shared.config import load_settings


def test_settings_repr_hides_secrets() -> None:
    s = load_settings(
        {
            "TG_API_ID": "12345",
            "TG_API_HASH": "hashsecret",
            "TG_SESSION": "sessionsecret",
            "WEB_PASSWORD_HASH": "pwsecret",
            "WEB_SECRET_KEY": "keysecret",
        }
    )
    text = repr(s)
    for secret in ("hashsecret", "sessionsecret", "pwsecret", "keysecret"):
        assert secret not in text
    assert s.tg_api_id == 12345


def test_defaults() -> None:
    s = load_settings({})
    assert s.notifier == "log"
    assert s.log_level == "INFO"
    assert s.tg_api_id is None


def test_unknown_notifier_rejected() -> None:
    with pytest.raises(ValueError, match="unknown NOTIFIER: email"):
        load_settings({"NOTIFIER": "email"})


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_values_use_defaults(blank: str) -> None:
    s = load_settings({"NOTIFIER": blank, "DB_PATH": blank, "LOG_LEVEL": blank})
    assert s.notifier == "log"
    assert s.db_path == Path("./data/velkgram.db")
    assert s.log_level == "INFO"


def test_retention_days_default_is_90() -> None:
    assert load_settings({}).retention_days == 90
    assert load_settings({"RETENTION_DAYS": "30"}).retention_days == 30


def test_retention_days_below_30_is_rejected() -> None:
    with pytest.raises(ValueError, match="RETENTION_DAYS"):
        load_settings({"RETENTION_DAYS": "29"})


def test_retention_days_not_a_number_is_rejected() -> None:
    with pytest.raises(ValueError, match="RETENTION_DAYS"):
        load_settings({"RETENTION_DAYS": "abc"})


def test_app_timezone_default_is_sao_paulo() -> None:
    assert load_settings({}).app_timezone == ZoneInfo("America/Sao_Paulo")
    assert load_settings({"APP_TIMEZONE": "UTC"}).app_timezone == ZoneInfo("UTC")


def test_unknown_app_timezone_is_rejected() -> None:
    with pytest.raises(ValueError, match="APP_TIMEZONE"):
        load_settings({"APP_TIMEZONE": "Mars/Base"})


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_retention_and_timezone_mean_default(blank: str) -> None:
    s = load_settings({"RETENTION_DAYS": blank, "APP_TIMEZONE": blank})
    assert s.retention_days == 90
    assert s.app_timezone == ZoneInfo("America/Sao_Paulo")
