"""Seed the superadmin user. Idempotent; safe to run on every deploy.

Usage: SUPERADMIN_EMAIL=neil@... python -m api.seed
"""

import sys

from sqlmodel import Session, select

from api.config import get_settings
from api.db import get_engine, init_db
from api.models import User


def seed() -> str:
    settings = get_settings()
    if not settings.superadmin_email:
        return "SUPERADMIN_EMAIL is not set; nothing to seed"
    init_db()
    with Session(get_engine()) as session:
        user = session.exec(select(User).where(User.email == settings.superadmin_email)).first()
        if user is None:
            user = User(email=settings.superadmin_email, is_superadmin=True)
            session.add(user)
            session.commit()
            return f"Seeded superadmin {settings.superadmin_email}"
        if not user.is_superadmin:
            user.is_superadmin = True
            session.add(user)
            session.commit()
            return f"Promoted existing user {settings.superadmin_email} to superadmin"
        return f"Superadmin {settings.superadmin_email} already present"


if __name__ == "__main__":
    print(seed())
    sys.exit(0)
