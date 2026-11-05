from collections.abc import AsyncIterator

import pytest

from tests.apps.test_collector_assembly import LIVE_COLLECTORS


@pytest.fixture(autouse=True)
async def _stop_offer_workers() -> AsyncIterator[None]:
    yield
    for c in LIVE_COLLECTORS:
        await c.stop_offer_worker()
    LIVE_COLLECTORS.clear()
