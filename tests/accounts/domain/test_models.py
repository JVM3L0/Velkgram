import pytest

from velkgram.accounts import InvalidUser, validate_password, validate_username


@pytest.mark.parametrize("raw", ["ana", "Ana.Silva", "joao_99", "a-b-c", "x" * 32])
def test_valid_usernames_are_kept_as_typed_but_trimmed(raw: str) -> None:
    assert validate_username(f"  {raw} ") == raw


@pytest.mark.parametrize("raw", ["", "ab", "x" * 33, "ana silva", "ana@x", "João", "-ana", "a/b"])
def test_invalid_usernames_are_rejected_in_portuguese(raw: str) -> None:
    with pytest.raises(InvalidUser) as exc:
        validate_username(raw)
    assert exc.value.message_pt


def test_password_needs_eight_characters() -> None:
    validate_password("12345678")
    with pytest.raises(InvalidUser):
        validate_password("1234567")
    with pytest.raises(InvalidUser):
        validate_password("a" * 201)
