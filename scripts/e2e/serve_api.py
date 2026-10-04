"""Run the API for the signed-in page tests (CI only): Clerk is bypassed by
overriding the auth dependency with the seeded superadmin in the seeded org.
Never deployed; nothing in the app imports this.

Usage: DATABASE_URL=sqlite:///e2e.db python scripts/e2e/serve_api.py [port]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import uvicorn  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from api.auth import AuthedUser, get_current_user  # noqa: E402
from api.db import get_engine  # noqa: E402
from api.main import app  # noqa: E402
from api.models import User  # noqa: E402


def _user() -> AuthedUser:
    with Session(get_engine()) as s:
        user = s.exec(select(User).where(User.clerk_user_id == "user_e2e")).one()
        s.expunge(user)
    return AuthedUser(user=user, org_id="org_e2e", org_role="org:admin")


app.dependency_overrides[get_current_user] = _user

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
