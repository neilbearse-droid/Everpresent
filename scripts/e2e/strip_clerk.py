"""Remove Clerk from a copy of the Next app so signed-in pages can render in
CI without a Clerk instance (CI only; run on a throwaway checkout or copy).
The API side is covered by serve_api.py's auth override.

Usage: python scripts/e2e/strip_clerk.py app
"""

import re
import sys
from pathlib import Path


def strip(app: Path) -> None:
    src = app / "src"

    def edit(rel: str, fn) -> None:
        p = src / rel
        before = p.read_text()
        after = fn(before)
        if after == before:
            raise SystemExit(f"strip_clerk: no change in {rel}; update this script")
        p.write_text(after)

    # Every server file that forwards the Clerk token: forward none instead.
    token = re.compile(r"const \{ getToken \} = await auth\(\);\n\s*"
                       r"const token = await getToken\(\);")
    for f in src.rglob("*.ts*"):
        s = f.read_text()
        if 'import { auth } from "@clerk/nextjs/server";' in s and "getToken" in s:
            s = s.replace('import { auth } from "@clerk/nextjs/server";', "")
            s = token.sub(r"const token: string | null = null;", s)
            f.write_text(s)
    edit("app/layout.tsx", lambda s: re.sub(r"<ClerkProvider[^>]*>", "<>", s.replace(
        'import { ClerkProvider } from "@clerk/nextjs";', "")).replace("</ClerkProvider>", "</>"))
    edit("components/dash-nav.tsx", lambda s: re.sub(
        r"<OrganizationSwitcher[\s\S]*?\n {10}/>", '<span className="text-xs">E2E org</span>',
        re.sub(r'import \{[^}]*\} from "@clerk/nextjs";\n', "", s))
        .replace("<UserButton />", "<span />"))
    edit("app/page.tsx", lambda s: s.replace('import { auth } from "@clerk/nextjs/server";', "")
         .replace("const { userId } = await auth();", "const userId = null as string | null;"))
    (src / "middleware.ts").write_text(
        "export default function middleware() {}\nexport const config = { matcher: [] };\n")
    (src / "app/sign-in/[[...sign-in]]/page.tsx").write_text(
        "export default function SignIn() { return <main>sign-in stub</main>; }\n")
    left = [str(f) for f in src.rglob("*.ts*") if "@clerk/" in f.read_text()]
    if left:
        raise SystemExit(f"strip_clerk: Clerk still imported in {left}")


if __name__ == "__main__":
    strip(Path(sys.argv[1] if len(sys.argv) > 1 else "app"))
    print("Clerk stripped")
