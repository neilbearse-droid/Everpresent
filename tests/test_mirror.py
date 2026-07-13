"""BigQuery mirror (§5.3): watermarked, idempotent, metadata-only, and a
clean skip when unconfigured. Network is faked — CI never talks to Google."""

import pytest

from tests.test_dashboards import processed_run  # noqa: F401  (fixtures)
from tests.test_processing import configured_tenant  # noqa: F401
from tests.test_runs import (  # noqa: F401  (fixtures)
    _pending_run,
    fake_retrieve,
    job_env,
    make_tenant,
)
from worker import mirror as mirror_mod


@pytest.fixture()
def bq_env(db_session, monkeypatch, tmp_path):
    from api.config import get_settings

    key_file = tmp_path / "sa.json"
    key_file.write_text('{"client_email": "svc@test.iam", "private_key": "unused"}')
    monkeypatch.setenv("BIGQUERY_PROJECT", "test-project")
    monkeypatch.setenv("BIGQUERY_DATASET", "everpresent_v3")
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", str(key_file))
    get_settings.cache_clear()
    monkeypatch.setattr(mirror_mod, "get_engine", lambda: db_session.get_bind())
    monkeypatch.setattr(mirror_mod, "_access_token", lambda client: "fake-token")
    created: list[str] = []
    inserted: dict[str, list[dict]] = {}
    monkeypatch.setattr(
        mirror_mod, "_ensure_table", lambda client, token, table, columns: created.append(table)
    )
    monkeypatch.setattr(
        mirror_mod,
        "_insert_all",
        lambda client, token, table, rows: inserted.setdefault(table, []).extend(rows),
    )
    yield created, inserted
    get_settings.cache_clear()


def test_mirror_skips_when_unconfigured(db_session, monkeypatch):
    from api.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setattr(mirror_mod, "get_engine", lambda: db_session.get_bind())
    assert mirror_mod.mirror_to_bigquery() == {}


def test_mirror_ships_new_rows_and_watermarks(processed_run, bq_env):  # noqa: F811
    created, inserted = bq_env

    counts = mirror_mod.mirror_to_bigquery()
    # 6 results (4 search + 2 nosearch), 12 mentions, 8 citations, 2 rollups.
    assert counts == {
        "runs_v3": 1,
        "results_v3": 6,
        "mentions_v3": 12,
        "citations_v3": 8,
        "visibility_daily_v3": 2,
    }
    assert set(created) == set(counts)

    # Metadata only: no raw payload URIs in the warehouse.
    result_row = inserted["results_v3"][0]["json"]
    assert "raw_uri" not in result_row
    assert result_row["query_text"]
    assert inserted["runs_v3"][0]["insertId"] == "runs_v3-1"

    # Watermarked: a second pass ships nothing.
    assert mirror_mod.mirror_to_bigquery() == {}
