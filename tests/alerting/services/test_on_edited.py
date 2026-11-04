from dataclasses import replace
from datetime import timedelta

from tests.alerting.services.test_evaluate import Harness
from tests.fakes.messages import NOW, msg
from velkgram.shared.events import MessageEdited, MessageReceived


def _edit(text: str, age: timedelta = timedelta(0)) -> MessageEdited:
    m = replace(msg(text=text), date=NOW - age)
    return MessageEdited(message=m, version=2, edited_at=NOW, sold_out_hint=False)


async def test_edit_that_newly_matches_alerts_once() -> None:
    h = Harness()
    h.wish()
    await h.evaluator.on_received(MessageReceived(msg(text="promo geral")))
    await h.evaluator.wait_idle()
    assert h.stored() == []
    e = _edit("RTX 4060 por R$ 1.500,00")
    await h.evaluator.on_edited(e)
    await h.evaluator.wait_idle()
    await h.evaluator.on_edited(e)
    await h.evaluator.wait_idle()
    assert len(h.stored()) == 1
    assert len(h.notifier.sent) == 1


async def test_edit_of_old_message_is_ignored() -> None:
    h = Harness()
    h.wish()
    await h.evaluator.on_edited(_edit("RTX 4060 por R$ 1.500,00", timedelta(minutes=31)))
    await h.evaluator.wait_idle()
    assert h.stored() == []
    assert h.notifier.sent == []
