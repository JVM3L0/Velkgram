from velkgram.offers.domain.channel_page import PostImage, oldest_post_id, parse_channel_page

CDN = "https://cdn1.telesco.pe/file/abc123_-XYZ.jpg"

PAGE = f"""
<div class="tgme_widget_message_wrap js-widget_message_wrap">
<div class="tgme_widget_message js-widget_message"
 data-post="promotom/114265" data-view="x">
<div class="tgme_widget_message_text js-message_text">Cupom sem foto</div>
<a class="tgme_widget_message_link_preview" href="https://s.shopee.com.br/x"><div>site</div></a>
</div></div>
<div class="tgme_widget_message_wrap js-widget_message_wrap">
<div class="tgme_widget_message js-widget_message"
 data-post="promotom/114266" data-view="y">
<a class="tgme_widget_message_photo_wrap 5166 1202_46" href="https://t.me/promotom/114266"
 style="width:800px;background-image:url('{CDN}')"></a>
<div class="tgme_widget_message_text js-message_text">Fone</div>
</div></div>
<div class="tgme_widget_message_wrap js-widget_message_wrap">
<div class="tgme_widget_message js-widget_message"
 data-post="promotom/114267" data-view="z">
<i class="tgme_widget_message_user_photo"><img src="https://cdn1.telesco.pe/file/avatar.jpg"></i>
<i class="emoji" style="background-image:url('//telegram.org/img/emoji/40/F09F94B8.png')"></i>
</div></div>
"""


def test_parse_returns_the_photo_url_of_each_post_that_has_one() -> None:
    assert parse_channel_page(PAGE) == [PostImage(114266, CDN)]


def test_parse_ignores_emoji_avatars_and_posts_without_a_photo() -> None:
    posts = PAGE.split('<div class="tgme_widget_message_wrap')
    assert parse_channel_page(posts[1]) == []  # link preview without an image
    assert parse_channel_page(posts[3]) == []  # avatar and emoji only


def test_parse_decodes_html_entities_in_the_url() -> None:
    page = (
        '<div data-post="c/9"><a class="tgme_widget_message_photo_wrap" '
        "style=\"background-image:url('https://cdn4.telesco.pe/file/a&amp;b.jpg')\"></a></div>"
    )
    assert parse_channel_page(page) == [PostImage(9, "https://cdn4.telesco.pe/file/a&b.jpg")]


def test_parse_only_trusts_telegram_cdn_hosts() -> None:
    page = (
        '<div data-post="c/9"><a class="tgme_widget_message_photo_wrap" '
        "style=\"background-image:url('https://evil.test/file/a.jpg')\"></a></div>"
        '<div data-post="c/10"><a class="tgme_widget_message_photo_wrap" '
        "style=\"background-image:url('http://cdn1.telesco.pe/file/a.jpg')\"></a></div>"
    )
    assert parse_channel_page(page) == []


def test_parse_keeps_the_first_photo_of_an_album_post() -> None:
    def wrap(n: int) -> str:
        return (
            '<a class="tgme_widget_message_photo_wrap" '
            f"style=\"background-image:url('https://cdn1.telesco.pe/file/{n}.jpg')\"></a>"
        )

    page = f'<div data-post="c/9">{wrap(1)}{wrap(2)}</div>'
    assert parse_channel_page(page) == [PostImage(9, "https://cdn1.telesco.pe/file/1.jpg")]


def test_parse_skips_malformed_post_ids_and_empty_pages() -> None:
    assert parse_channel_page("") == []
    assert parse_channel_page('<div data-post="c/notanumber">x</div>') == []


def test_oldest_post_id_counts_posts_without_a_photo_too() -> None:
    assert oldest_post_id(PAGE) == 114265
    assert oldest_post_id("") is None
    assert oldest_post_id('<div data-post="c/notanumber">x</div>') is None
