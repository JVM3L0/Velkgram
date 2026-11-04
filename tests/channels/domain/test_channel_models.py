import pytest

from velkgram.channels import InvalidChannel, parse_channel_ref


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://t.me/promotech", "@promotech"),
        ("http://t.me/promotech", "@promotech"),
        ("t.me/promotech", "@promotech"),
        ("@promotech", "@promotech"),
        ("  promotech  ", "@promotech"),
        ("https://t.me/promotech/", "@promotech"),
        ("t.me/+AbC12", "+AbC12"),
        ("https://t.me/+AbC12", "+AbC12"),
        ("t.me/joinchat/AbC12", "+AbC12"),
    ],
)
def test_parse_channel_ref(raw: str, expected: str) -> None:
    assert parse_channel_ref(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "-1001234",
        "1234",
        "t.me/c/123/4",
        "",
        "   ",
        "@",
        "t.me/",
        "two words",
        "https://x.com/promotech",
    ],
)
def test_parse_channel_ref_rejects(raw: str) -> None:
    with pytest.raises(InvalidChannel) as exc:
        parse_channel_ref(raw)
    assert exc.value.message_pt == "Use @canal ou um link t.me"
