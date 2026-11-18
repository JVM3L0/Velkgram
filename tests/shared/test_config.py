from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from velkgram.shared.config import Settings, load_settings


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


def test_notifier_default_and_blank_are_log() -> None:
    assert load_settings({}).notifier == "log"
    assert load_settings({"NOTIFIER": ""}).notifier == "log"


def test_telegram_without_token_is_rejected() -> None:
    with pytest.raises(ValueError, match="ALERT_BOT_TOKEN is required when NOTIFIER=telegram"):
        load_settings({"NOTIFIER": "telegram"})


@pytest.mark.parametrize("chat", ["42", "-1001234567890"])
def test_telegram_with_token_and_chat_id(chat: str) -> None:
    s = load_settings({"NOTIFIER": "telegram", "ALERT_BOT_TOKEN": "1:tok", "ALERT_CHAT_ID": chat})
    assert s.notifier == "telegram"
    assert s.alert_bot_token == "1:tok"
    assert s.alert_chat_id == int(chat)


def test_chat_id_is_optional() -> None:
    s = load_settings({"NOTIFIER": "telegram", "ALERT_BOT_TOKEN": "1:tok"})
    assert s.alert_chat_id is None


def test_bad_chat_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="ALERT_CHAT_ID"):
        load_settings({"ALERT_CHAT_ID": "abc"})


def test_repr_masks_bot_token_and_shows_chat_id() -> None:
    s = load_settings(
        {"NOTIFIER": "telegram", "ALERT_BOT_TOKEN": "123:SECRET", "ALERT_CHAT_ID": "-5"}
    )
    text = repr(s)
    assert "SECRET" not in text
    assert "alert_chat_id=-5" in text


@pytest.mark.parametrize(
    ("raw", "expected"), [("", False), ("0", False), ("1", True), ("true", True)]
)
def test_web_https_only_flag(raw: str, expected: bool) -> None:
    assert load_settings({"WEB_HTTPS_ONLY": raw}).web_https_only is expected


def test_the_image_copies_live_next_to_the_database_by_default() -> None:
    s = load_settings({"DB_PATH": "/app/data/velkgram.db"})
    assert s.images_dir is None
    assert s.images_path == Path("/app/data/images")
    assert s.images_max_mb == 1024


def test_the_image_directory_and_budget_can_be_set() -> None:
    s = load_settings({"IMAGES_DIR": "/pics", "IMAGES_MAX_MB": "256"})
    assert (s.images_path, s.images_max_mb) == (Path("/pics"), 256)


@pytest.mark.parametrize("raw", ["abc", "15", "-1"])
def test_a_bad_image_budget_is_refused(raw: str) -> None:
    with pytest.raises(ValueError, match="IMAGES_MAX_MB"):
        load_settings({"IMAGES_MAX_MB": raw})


def test_settings_built_by_hand_keep_the_images_next_to_their_database(tmp_path: Path) -> None:
    assert Settings(db_path=tmp_path / "x.db").images_path == tmp_path / "images"
