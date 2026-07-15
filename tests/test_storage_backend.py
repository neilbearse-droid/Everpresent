"""Raw-payload storage backends: the file backend (VPS) and the db backend
(Render, no shared disk). Both round-trip the same envelope via the same URI."""

import pytest


@pytest.fixture()
def _clear_settings():
    from api.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_file_backend_round_trip(monkeypatch, tmp_path, _clear_settings):
    monkeypatch.setenv("STORAGE_BACKEND", "file")
    monkeypatch.setenv("RAW_STORAGE_DIR", str(tmp_path))
    from api.storage import read_raw_envelope, write_raw_envelope

    uri = write_raw_envelope("smith", 7, "result-0001", {"parsed_text": "hi", "n": 1})
    assert uri == "smith/run-7/result-0001.json"
    assert (tmp_path / uri).is_file()
    assert read_raw_envelope(uri) == {"parsed_text": "hi", "n": 1}
    assert read_raw_envelope("../escape.json") is None


def test_db_backend_round_trip(db_session, monkeypatch, _clear_settings):
    monkeypatch.setenv("STORAGE_BACKEND", "db")
    import api.storage as storage

    monkeypatch.setattr("api.db.get_engine", lambda: db_session.get_bind())

    uri = write_and_read = storage.write_raw_envelope(
        "smith", 3, "result-b-0000", {"parsed_text": "web answer", "surface": "chatgpt_web"}
    )
    assert uri == "smith/run-3/result-b-0000.json"
    # No file written for the db backend.
    got = storage.read_raw_envelope(uri)
    assert got == {"parsed_text": "web answer", "surface": "chatgpt_web"}
    assert storage.read_raw_envelope("smith/run-3/missing.json") is None
    assert write_and_read  # uri is truthy


def test_db_backend_overwrites_on_reprocess(db_session, monkeypatch, _clear_settings):
    monkeypatch.setenv("STORAGE_BACKEND", "db")
    from sqlmodel import select

    import api.storage as storage
    from api.models import RawPayload

    monkeypatch.setattr("api.db.get_engine", lambda: db_session.get_bind())

    storage.write_raw_envelope("smith", 1, "r", {"v": 1})
    storage.write_raw_envelope("smith", 1, "r", {"v": 2})
    rows = db_session.exec(select(RawPayload).where(RawPayload.uri == "smith/run-1/r.json")).all()
    assert len(rows) == 1  # upsert, not duplicate
    assert storage.read_raw_envelope("smith/run-1/r.json") == {"v": 2}
