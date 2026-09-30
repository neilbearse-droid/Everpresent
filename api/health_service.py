"""Deep system health: is the database up, is Redis up, is a worker actually
draining each queue, is the scheduler ticking?

`/api/health` stays a cheap liveness probe (Render gates deploys and restarts
on it — a Redis blip must not restart a perfectly good API). This module backs
`/api/health/deep` (for an uptime monitor) and the System row on the admin
readiness panel, so "worker died overnight" is visible before a demo, not
discovered when runs sit at pending."""

import time
from typing import Any

from redis import Redis
from rq import Queue, Worker
from sqlalchemy import text
from sqlmodel import Session

from api.config import get_settings

SCHEDULER_HEARTBEAT_KEY = "everpresent:heartbeat:scheduler"
# RQ refreshes a worker's heartbeat at least every worker_ttl (420s by
# default), even while idle; past 10 minutes it's gone.
WORKER_STALE_S = 600
# The scheduler ticks every 30s.
SCHEDULER_STALE_S = 180

QUEUES = {
    "default": "Worker: API engines",
    "scrape": "Worker: browser engines",
}


def _redis() -> Redis:
    return Redis.from_url(
        get_settings().redis_url, socket_connect_timeout=2, socket_timeout=2
    )


def beat_scheduler(conn: Redis | None = None) -> None:
    """Stamp the scheduler heartbeat. Never raises: a Redis blip must not
    break the scheduler loop."""
    try:
        (conn or _redis()).set(SCHEDULER_HEARTBEAT_KEY, str(time.time()), ex=SCHEDULER_STALE_S * 4)
    except Exception:  # noqa: BLE001
        pass


def _ago(seconds: float) -> str:
    s = int(max(seconds, 0))
    if s < 90:
        return f"{s}s ago"
    if s < 90 * 60:
        return f"{s // 60}m ago"
    return f"{s // 3600}h ago"


def system_checks(session: Session) -> list[dict[str, Any]]:
    """[{label, ok, hint}] in the readiness-check shape."""
    checks: list[dict[str, Any]] = []

    try:
        session.exec(text("SELECT 1"))  # type: ignore[call-overload]
        checks.append({"label": "Database", "ok": True, "hint": "Connected."})
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        checks.append({
            "label": "Database", "ok": False,
            "hint": f"Unreachable ({type(exc).__name__}). Check everpresent-db on Render.",
        })

    try:
        conn = _redis()
        conn.ping()
    except Exception as exc:  # noqa: BLE001
        checks.append({
            "label": "Redis (job queue)", "ok": False,
            "hint": f"Unreachable ({type(exc).__name__}). Runs can't be queued. "
            "Check everpresent-redis on Render.",
        })
        for label in (*QUEUES.values(), "Scheduler"):
            checks.append({"label": label, "ok": False, "hint": "Unknown: Redis is down."})
        return checks
    checks.append({"label": "Redis (job queue)", "ok": True, "hint": "Connected."})

    now = time.time()
    try:
        workers = Worker.all(connection=conn)
    except Exception:  # noqa: BLE001
        workers = []
    for queue, label in QUEUES.items():
        beats = [
            w.last_heartbeat.timestamp()
            for w in workers
            if w.last_heartbeat is not None and queue in w.queue_names()
        ]
        fresh = [b for b in beats if now - b <= WORKER_STALE_S]
        try:
            waiting = Queue(queue, connection=conn).count
        except Exception:  # noqa: BLE001
            waiting = 0
        backlog = f" {waiting} job(s) waiting." if waiting else ""
        if fresh:
            checks.append({
                "label": label, "ok": True,
                "hint": f"Alive, last heartbeat {_ago(now - max(fresh))}.{backlog}",
            })
        else:
            checks.append({
                "label": label, "ok": False,
                "hint": (
                    f"No live worker (last heartbeat {_ago(now - max(beats))})."
                    if beats else "No worker has registered."
                ) + f"{backlog} Restart everpresent-worker on Render.",
            })

    raw = None
    try:
        raw = conn.get(SCHEDULER_HEARTBEAT_KEY)
    except Exception:  # noqa: BLE001
        pass
    if raw is None:
        checks.append({
            "label": "Scheduler", "ok": False,
            "hint": "No heartbeat. Scheduled runs won't fire. Restart everpresent-worker.",
        })
    else:
        age = now - float(raw)
        checks.append({
            "label": "Scheduler",
            "ok": age <= SCHEDULER_STALE_S,
            "hint": f"Last tick {_ago(age)}."
            + ("" if age <= SCHEDULER_STALE_S else " Restart everpresent-worker."),
        })
    return checks
