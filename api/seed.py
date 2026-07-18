"""Idempotent seed, run by the deploy script after `alembic upgrade head`:

1. the superadmin user row (SUPERADMIN_EMAIL, linked to Clerk on first login);
2. the launch tenants (smith, greenshield) with their YAML configs from
   seeds/ — imported only when the tenant doesn't exist yet, so admin-panel
   edits and re-imports are never clobbered by a deploy.

Usage: python -m api.seed
"""

import sys
from pathlib import Path

from sqlmodel import Session, select

from api.config import get_settings
from api.db import get_engine
from api.models import Tenant, User
from api.yaml_import import import_config, parse_config_yaml

SEEDS_DIR = Path(__file__).resolve().parent.parent / "seeds"

LAUNCH_TENANTS = {
    "smith": "Smith School of Business",
    "greenshield": "GreenShield",
    "godaddy": "GoDaddy",
}


def seed_superadmin(session: Session) -> str:
    email = get_settings().superadmin_email
    if not email:
        return "SUPERADMIN_EMAIL is not set; skipping superadmin seed"
    user = session.exec(select(User).where(User.email == email)).first()
    if user is None:
        session.add(User(email=email, is_superadmin=True))
        session.commit()
        return f"Seeded superadmin {email}"
    if not user.is_superadmin:
        user.is_superadmin = True
        session.add(user)
        session.commit()
        return f"Promoted existing user {email} to superadmin"
    return f"Superadmin {email} already present"


def seed_launch_tenants(session: Session) -> list[str]:
    messages = []
    for slug, name in LAUNCH_TENANTS.items():
        tenant = session.exec(select(Tenant).where(Tenant.slug == slug)).first()
        if tenant is not None:
            messages.append(f"Tenant {slug} already present")
            continue
        tenant = Tenant(name=name, slug=slug)
        session.add(tenant)
        session.flush()
        seed_file = SEEDS_DIR / f"{slug}.yaml"
        if seed_file.exists():
            spec = parse_config_yaml(seed_file.read_text(encoding="utf-8"))
            counts = import_config(session, tenant, spec)
            messages.append(f"Created tenant {slug} and imported seed config: {counts}")
        else:
            messages.append(f"Created tenant {slug} (no seed file at {seed_file})")
        session.commit()
    return messages


def seed() -> list[str]:
    with Session(get_engine()) as session:
        messages = [seed_superadmin(session)]
        messages.extend(seed_launch_tenants(session))
    return messages


if __name__ == "__main__":
    for line in seed():
        print(line)
    sys.exit(0)
