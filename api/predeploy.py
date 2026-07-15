"""Pre-deploy step for managed hosts (Render): apply migrations, then seed.

A single command with no shell operators, so it runs identically however the
platform invokes it (Render parses preDeployCommand itself rather than through
a full shell, so chaining with `&&` is unreliable — see render.yaml)."""

import subprocess
import sys


def main() -> int:
    print(">>> alembic upgrade head", flush=True)
    result = subprocess.run(["alembic", "upgrade", "head"])
    if result.returncode != 0:
        print("!!! migrations failed", flush=True)
        return result.returncode

    print(">>> seeding", flush=True)
    from api.seed import seed

    for line in seed():
        print(line, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
