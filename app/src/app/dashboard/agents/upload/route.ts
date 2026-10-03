import { auth } from "@clerk/nextjs/server";

const API_ORIGIN = process.env.API_ORIGIN ?? "http://localhost:8000";
// The API enforces the real limit (200 MB uncompressed); this only refuses
// bodies that are obviously too big before streaming them upstream.
const MAX_WIRE_BYTES = 200 * 1024 * 1024;

/** Route handlers don't get Server Actions' built-in CSRF check: only accept
 * same-origin requests (the upload form), never a cross-site form post. */
function sameOrigin(request: Request): boolean {
  const origin = request.headers.get("origin");
  if (!origin) return request.headers.get("sec-fetch-site") === "same-origin";
  try {
    // Behind a proxy (Render) the public host may arrive as x-forwarded-host.
    const host = new URL(origin).host;
    return host === request.headers.get("x-forwarded-host") || host === request.headers.get("host");
  } catch {
    return false;
  }
}

/** Streams an access-log upload through to the API (the browser never holds
 * the API token, and large files never sit in a server-action body). */
export async function POST(request: Request) {
  if (!sameOrigin(request)) return new Response("Cross-site upload refused", { status: 403 });
  const declared = Number(request.headers.get("content-length") ?? "0");
  if (declared > MAX_WIRE_BYTES) {
    return new Response(
      JSON.stringify({ detail: "log file too large (max 200 MB); split it" }),
      { status: 413, headers: { "Content-Type": "application/json" } },
    );
  }
  const { getToken } = await auth();
  const token = await getToken();
  if (!request.body) return new Response("No file", { status: 400 });
  let upstream: Response;
  try {
    upstream = await fetch(`${API_ORIGIN}/api/tenant/agent-logs`, {
      method: "POST",
      headers: {
        "Content-Type": "application/octet-stream",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: request.body,
      // Required by Node fetch to stream a request body.
      // @ts-expect-error duplex is not in the DOM RequestInit type yet
      duplex: "half",
      cache: "no-store",
    });
  } catch {
    return new Response("The API is unreachable. Try again shortly.", { status: 502 });
  }
  return new Response(await upstream.text(), {
    status: upstream.status,
    headers: { "Content-Type": upstream.headers.get("content-type") ?? "application/json" },
  });
}
