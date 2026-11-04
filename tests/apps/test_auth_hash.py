import pytest

from velkgram.apps.web.auth import hash_password, verify_password


def test_hash_and_verify_round_trip() -> None:
    stored = hash_password("s3cret")
    assert stored.startswith("scrypt$16384$8$1$")
    assert len(stored.split("$")) == 6
    assert verify_password(stored, "s3cret")


def test_hash_is_salted() -> None:
    assert hash_password("x") != hash_password("x")


def test_verify_rejects_wrong_password() -> None:
    assert not verify_password(hash_password("s3cret"), "other")


def test_verify_never_raises_on_malformed_input() -> None:
    for bad in ("", "garbage", "scrypt$a$b$c$d$e", "bcrypt$1$2$3$4$5", "scrypt$16384$8$1$!!$!!"):
        assert verify_password(bad, "x") is False


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "bcrypt$16384$8$1$QQ==$QQ==",
        "scrypt$16384$8$1$QQ==",
        "scrypt$99999999999999999999$8$1$QQ==$QQ==",
        "scrypt$16384$99999999999999999999$1$QQ==$QQ==",
        "scrypt$16384$8$99999999999999999999$QQ==$QQ==",
        "scrypt$-16384$8$1$QQ==$QQ==",
        "scrypt$16384$-8$1$QQ==$QQ==",
        "scrypt$16384$8$-1$QQ==$QQ==",
        "scrypt$0$8$1$QQ==$QQ==",
        "scrypt$16384$0$1$QQ==$QQ==",
        "scrypt$16384$8$0$QQ==$QQ==",
        f"scrypt${2**22}$8$1$QQ==$QQ==",
        "scrypt$16384$8$1$!!$QQ==",
        "scrypt$16384$8$1$QQ==$!!",
    ],
)
def test_verify_rejects_hostile_input(bad: str) -> None:
    assert verify_password(bad, "x") is False
