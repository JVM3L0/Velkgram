import asyncio


class FakeBotClient:
    """Records calls; scriptable errors; calls can be gated on events."""

    def __init__(self, monotonic: "FakeMonotonic | None" = None) -> None:
        self._monotonic = monotonic
        self.start_calls: list[str] = []
        self.sent: list[tuple[int, str, bool]] = []
        self.send_times: list[float] = []
        self.disconnects = 0
        self.start_error: Exception | None = None
        self.send_error: Exception | None = None
        self.start_gate: asyncio.Event | None = None
        self.send_gate: asyncio.Event | None = None
        self.disconnect_gate: asyncio.Event | None = None

    async def start(self, bot_token: str) -> None:
        self.start_calls.append(bot_token)
        if self.start_gate is not None:
            await self.start_gate.wait()
        if self.start_error is not None:
            raise self.start_error

    async def send_message(self, chat_id: int, text: str, *, link_preview: bool) -> None:
        if self._monotonic is not None:
            self.send_times.append(self._monotonic())
        if self.send_gate is not None:
            await self.send_gate.wait()
        if self.send_error is not None:
            raise self.send_error
        self.sent.append((chat_id, text, link_preview))

    async def disconnect(self) -> None:
        self.disconnects += 1
        if self.disconnect_gate is not None:
            await self.disconnect_gate.wait()


class FakeMonotonic:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.value

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.value += seconds
