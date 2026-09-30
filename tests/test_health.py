"""Deep health: database, Redis, workers and scheduler are reported honestly,
and the cheap liveness probe never depends on them."""

import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import api.health_service as hs


class _FakeRedis:
    def __init__(self, store=None, down=False):
        self.store = store or {}
        self.down = down

    def ping(self):
        if self.down:
            raise ConnectionError("down")
        return True

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.store[key] = value


def _worker(queues, age_s):
    beat = datetime.now(UTC) - timedelta(seconds=age_s)
    return SimpleNamespace(last_heartbeat=beat, queue_names=lambda: queues)


def _patch(monkeypatch, redis, workers, waiting=0):
    monkeypatch.setattr(hs, "_redis", lambda: redis)
    monkeypatch.setattr(hs.Worker, "all", staticmethod(lambda connection: workers))
    monkeypatch.setattr(hs, "Queue", lambda name, connection: SimpleNamespace(count=waiting))


def _by_label(checks):
    return {c["label"]: c for c in checks}


def test_all_up(db_session, monkeypatch):
    redis = _FakeRedis({hs.SCHEDULER_HEARTBEAT_KEY: str(time.time() - 20)})
    _patch(monkeypatch, redis, [_worker(["default", "scrape"], 30)])
    checks = _by_label(hs.system_checks(db_session))
    assert all(c["ok"] for c in checks.values()), checks
    assert "30s ago" in checks["Worker: API engines"]["hint"]


def test_dead_worker_and_stalled_scheduler_are_flagged(db_session, monkeypatch):
    redis = _FakeRedis({hs.SCHEDULER_HEARTBEAT_KEY: str(time.time() - 3600)})
    _patch(monkeypatch, redis, [_worker(["default"], 30), _worker(["scrape"], 7200)], waiting=3)
    checks = _by_label(hs.system_checks(db_session))
    assert checks["Worker: API engines"]["ok"]
    assert not checks["Worker: browser engines"]["ok"]
    assert "3 job(s) waiting" in checks["Worker: browser engines"]["hint"]
    assert not checks["Scheduler"]["ok"]


def test_redis_down_marks_everything_downstream_unknown(db_session, monkeypatch):
    _patch(monkeypatch, _FakeRedis(down=True), [])
    checks = _by_label(hs.system_checks(db_session))
    assert checks["Database"]["ok"]
    assert not checks["Redis (job queue)"]["ok"]
    assert not checks["Scheduler"]["ok"]


def test_scheduler_beat_writes_the_key():
    redis = _FakeRedis()
    hs.beat_scheduler(redis)  # type: ignore[arg-type]
    assert hs.SCHEDULER_HEARTBEAT_KEY in redis.store


def test_liveness_stays_ok_and_deep_returns_503(client, monkeypatch):
    _patch(monkeypatch, _FakeRedis(down=True), [])
    assert client.get("/api/health").status_code == 200
    deep = client.get("/api/health/deep")
    assert deep.status_code == 503
    assert deep.json()["checks"]["Redis (job queue)"] is False
