"""Seed a database for the signed-in page tests (CI only).

Creates the GoDaddy tenant from seeds/godaddy.yaml, a superadmin, and four
weeks of synthetic runs across every surface, then runs normal processing on
each so every dashboard has real derived rows (mentions, rollups, playbook).
Deterministic: same seed, same data. No network.

Usage: DATABASE_URL=sqlite:///e2e.db python scripts/e2e/seed_signed_in.py
"""

import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlmodel import Session, select

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from api.db import get_engine  # noqa: E402
from api.models import (  # noqa: E402
    Citation,
    Intervention,
    Query,
    Result,
    ResultStatus,
    ResultVariant,
    Run,
    RunMode,
    RunStatus,
    SurfaceCode,
    Tenant,
    User,
)
from api.processing_service import process_run  # noqa: E402
from api.storage import write_raw_envelope  # noqa: E402
from api.yaml_import import import_config, parse_config_yaml  # noqa: E402

ORG_ID = "org_e2e"
SURFACES = [SurfaceCode.openai_api, SurfaceCode.claude_api, SurfaceCode.gemini_api,
            SurfaceCode.perplexity_api, SurfaceCode.google_aio, SurfaceCode.google_ai_mode]
RIVALS = ["Namecheap", "Wix", "Squarespace", "Hostinger", "Shopify", "Porkbun"]
DOMAINS = ["godaddy.com", "namecheap.com", "wix.com", "reddit.com", "forbes.com",
           "techradar.com", "youtube.com", "hostinger.com"]


def _answer(rng: random.Random, query: str) -> tuple[str, list[str]]:
    names = rng.sample(RIVALS, k=rng.randint(1, 3))
    if rng.random() < 0.45:
        names.insert(rng.randint(0, len(names)), "GoDaddy")
    lines = [f"For “{query}”, people usually look at {', '.join(names)}."]
    if "GoDaddy" in names:
        lines.append(rng.choice([
            "GoDaddy has strong templates but support can be slow.",
            "GoDaddy is easy for beginners, though renewal prices are higher.",
            "GoDaddy bundles email and domains in one place.",
        ]))
    urls = [f"https://www.{d}/{rng.randint(1, 40)}" for d in rng.sample(DOMAINS, k=3)]
    return "\n".join(lines), urls


def main() -> None:
    rng = random.Random(7)
    with Session(get_engine()) as s:
        if s.exec(select(Tenant).where(Tenant.slug == "godaddy")).first():
            print("already seeded")
            return
        s.add(User(email="e2e@example.com", clerk_user_id="user_e2e", is_superadmin=True))
        t = Tenant(name="GoDaddy", slug="godaddy", clerk_org_id=ORG_ID,
                   ai_processing_approved=True, monthly_spend_cap_usd=300)
        s.add(t)
        s.flush()
        assert t.id is not None
        spec = parse_config_yaml((ROOT / "seeds" / "godaddy.yaml").read_text())
        import_config(s, t, spec)
        s.commit()
        queries = [q.text for q in s.exec(select(Query).where(Query.tenant_id == t.id)).all()]
        today = datetime.now(UTC).replace(hour=13, minute=0, second=0, microsecond=0)
        for days_ago in (27, 24, 20, 17, 13, 10, 6, 3, 1):
            when = today - timedelta(days=days_ago)
            run = Run(tenant_id=t.id, trigger="schedule", status=RunStatus.complete,
                      surface_set=[str(x) for x in SURFACES], started_at=when,
                      finished_at=when + timedelta(minutes=20), created_at=when)
            s.add(run)
            s.flush()
            assert run.id is not None and t.id is not None
            for i, q in enumerate(queries):
                for surface in SURFACES:
                    text, urls = _answer(rng, q)
                    r = Result(run_id=run.id, tenant_id=t.id, query_text=q,
                               persona_name="Generic", persona_segment="generic",
                               surface=surface, mode=RunMode.A, variant=ResultVariant.search,
                               status=ResultStatus.ok, created_at=when,
                               served_model="model-a" if days_ago > 12 else "model-b")
                    r.raw_uri = write_raw_envelope(
                        t.slug, run.id, f"r-{i}-{surface}",
                        {"surface": str(surface), "parsed_text": text, "response": {}},
                        session=s)
                    s.add(r)
                    s.flush()
                    assert r.id is not None
                    for u in urls:
                        s.add(Citation(result_id=r.id, tenant_id=t.id, url=u,
                                       domain=u.split("/")[2].removeprefix("www.")))
            s.commit()
            run.counts = {"completed": len(queries) * len(SURFACES), **process_run(s, run)}
            s.add(run)
            s.commit()
        s.add(Intervention(tenant_id=t.id, query_text=queries[0], url="/domains",
                           description="Comparison table on the domains page",
                           shipped_at=today - timedelta(days=14)))
        s.commit()
        print(f"seeded {len(queries)} queries x {len(SURFACES)} surfaces x 9 runs")


if __name__ == "__main__":
    main()
