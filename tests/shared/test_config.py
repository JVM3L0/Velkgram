from pathlib import Path

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
