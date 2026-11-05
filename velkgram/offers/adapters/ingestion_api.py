"""MessageSource backed by the ingestion module's public API."""

from collections.abc import Iterator

from velkgram.ingestion import IngestionQueries
from velkgram.offers.ports.messages import SourceMessage


class IngestionApiMessageSource:
    def __init__(self, queries: IngestionQueries) -> None:
        self._queries = queries

    def iter_messages(self) -> Iterator[SourceMessage]:
        for stored in self._queries.iter_stored_messages():
            yield SourceMessage(stored.message, deleted=stored.deleted, sold_out=stored.sold_out)
