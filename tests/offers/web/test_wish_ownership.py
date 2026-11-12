from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.apps.web_support import make_client, make_settings, make_user_client
from velkgram.shared.db import connect

PATHS = (
    "/wishes/{id}",
    "/wishes/{id}/matches",
    "/wishes/{id}/chart",
    "/wishes/{id}/history",
)


@pytest.fixture
def setup(tmp_path: Path) -> tuple[TestClient, TestClient, int]:
    admin = make_client(tmp_path)
    ana = make_user_client(tmp_path, "ana")
    conn = connect(make_settings(tmp_path).db_path)
    try:
        cursor = conn.execute(
            "INSERT INTO wishes (name, required_terms, excluded_terms, max_price_cents, enabled, "
            "created_at, updated_at, user_id) "
            "VALUES ('Mine', '[\"x\"]', '[]', 1000, 1, 'x', 'x', 1)"
        )
        conn.commit()
        wish_id = int(cursor.lastrowid or 0)
    finally:
        conn.close()
    return admin, ana, wish_id


@pytest.mark.parametrize("path", PATHS)
def test_the_owner_sees_the_wish_pages(
    path: str, setup: tuple[TestClient, TestClient, int]
) -> None:
    admin, _, wish_id = setup
    assert admin.get(path.format(id=wish_id)).status_code == 200


@pytest.mark.parametrize("path", PATHS)
def test_another_user_gets_404_on_the_wish_pages(
    path: str, setup: tuple[TestClient, TestClient, int]
) -> None:
    _, ana, wish_id = setup
    assert ana.get(path.format(id=wish_id)).status_code == 404


def test_another_user_cannot_retry_the_history_of_someone_elses_wish(
    setup: tuple[TestClient, TestClient, int],
) -> None:
    _, ana, wish_id = setup
    assert ana.post(f"/wishes/{wish_id}/history/retry").status_code == 404


def test_the_owner_can_retry_the_history(setup: tuple[TestClient, TestClient, int]) -> None:
    admin, _, wish_id = setup
    assert admin.post(f"/wishes/{wish_id}/history/retry").status_code == 200
