import asyncio

from velkgram.alerting import AlertMessage, NotifierError


class FakeNotifier:
    def __init__(self, fail_times: int = 0, delay_s: float = 0.0) -> None:
        self._fail_times = fail_times
        self._delay_s = delay_s
        self.sent: list[AlertMessage] = []
        self.system: list[str] = []
        self.calls = 0

    async def notify(self, message: AlertMessage) -> None:
        self.calls += 1
        if self._delay_s:
            await asyncio.sleep(self._delay_s)
        if self.calls <= self._fail_times:
            raise NotifierError(f"boom {self.calls}")
        self.sent.append(message)

    async def notify_system(self, text: str) -> None:
        self.system.append(text)
