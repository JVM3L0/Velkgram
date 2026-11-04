from dataclasses import replace

from velkgram.wishlist import Wish


class InMemoryWishRepository:
    def __init__(self) -> None:
        self.version = 0
        self._wishes: dict[int, Wish] = {}
        self._next_id = 1

    def add(self, w: Wish) -> Wish:
        stored = replace(w, id=self._next_id)
        self._wishes[self._next_id] = stored
        self._next_id += 1
        self.version += 1
        return stored

    def update(self, w: Wish) -> None:
        if w.id is not None and w.id in self._wishes:
            self._wishes[w.id] = w
        self.version += 1

    def delete(self, id: int) -> None:
        self._wishes.pop(id, None)
        self.version += 1

    def get(self, id: int) -> Wish | None:
        return self._wishes.get(id)

    def list_all(self) -> list[Wish]:
        return [self._wishes[k] for k in sorted(self._wishes)]

    def list_enabled(self) -> list[Wish]:
        return [w for w in self.list_all() if w.enabled]
