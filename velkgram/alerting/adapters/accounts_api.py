"""Chat directory and active users backed by the accounts module's public API."""

from collections.abc import Callable

from velkgram.accounts import UserRepository

ADMIN_ID = 1


class AccountsChatDirectory:
    """User -> Telegram chat. The admin falls back to the bot's own chat (ALERT_CHAT_ID or the
    owner's account), so the owner keeps receiving alerts without setting anything."""

    def __init__(self, repo: UserRepository, admin_fallback: Callable[[], int | None]) -> None:
        self._repo = repo
        self._fallback = admin_fallback

    def chat_id(self, user_id: int) -> int | None:
        user = self._repo.get(user_id)
        if user is None or not user.enabled:
            return None
        if user.telegram_chat_id is not None:
            return user.telegram_chat_id
        return self._fallback() if user_id == ADMIN_ID else None


def active_user_ids(repo: UserRepository) -> Callable[[], frozenset[int]]:
    def ids() -> frozenset[int]:
        return frozenset(u.id for u in repo.list_all() if u.enabled and u.id is not None)

    return ids
