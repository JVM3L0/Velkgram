"""Read-only access to wishes, as matching views."""

from typing import Protocol

from velkgram.shared.deals import WishView


class WishReader(Protocol):
    def enabled(self) -> list[WishView]: ...

    def all(self) -> list[WishView]: ...
