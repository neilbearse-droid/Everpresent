"""Plan frequency caps: cron guard + the schedule-save gate."""

from api.scheduling import cron_within_cap
from tests.test_admin import as_superadmin, superadmin  # noqa: F401  (fixtures)


def test_cron_within_cap_catches_over_frequent_schedules():
    assert cron_within_cap("0 13 * * *", 1)       # daily — ok
    assert cron_within_cap("0 13 * * 1", 1)       # weekly — ok
    assert not cron_within_cap("0 * * * *", 1)    # hourly — too often
    assert not cron_within_cap("0 0,12 * * *", 1)  # twice daily — too often
    assert cron_within_cap("0 0,12 * * *", 2)     # twice daily — ok at cap 2
    assert cron_within_cap("0 * * * *", None)     # uncapped plan — anything goes


def test_put_schedule_enforces_plan_frequency(client, as_superadmin):  # noqa: F811
    client.post("/api/admin/tenants", json={"name": "Smith", "slug": "smith"})
    client.patch("/api/admin/tenants/smith", json={"plan": "monitor"})  # 1 run/day

    ok = client.put("/api/admin/tenants/smith/schedule",
                    json={"cron_expr": "0 13 * * *", "enabled": True})
    assert ok.status_code == 200

    hourly = client.put("/api/admin/tenants/smith/schedule",
                        json={"cron_expr": "0 * * * *", "enabled": True})
    assert hourly.status_code == 422
    assert "run/day" in hourly.json()["detail"]

    # Command is uncapped — the same hourly schedule is allowed.
    client.patch("/api/admin/tenants/smith", json={"plan": "command"})
    now_ok = client.put("/api/admin/tenants/smith/schedule",
                        json={"cron_expr": "0 * * * *", "enabled": True})
    assert now_ok.status_code == 200
