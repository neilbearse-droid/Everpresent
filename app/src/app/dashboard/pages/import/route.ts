import { auth } from "@clerk/nextjs/server";

const API_ORIGIN = process.env.API_ORIGIN ?? "http://localhost:8000";
const MAX_BYTES = 20 * 1024 * 1024;
const SOURCES = new Set(["gsc", "bing", "merchant", "cloudflare", "ga4", "other"]);

function sameOrigin(request: Request): boolean {
  const origin = request.headers.get("origin");
  if (!origin) return request.headers.get("sec-fetch-site") === "same-origin";
  try {
    const host = new URL(origin).host;
    return host === request.headers.get("x-forwarded-host") || host === request.headers.get("host");
  } catch {
    return false;
  }
}

/** Forwards a first-party CSV export to the API (same-origin only). */
export async function POST(request: Request) {
  if (!sameOrigin(request)) return new Response("Cross-site upload refused", { status: 403 });
  const source = new URL(request.url).searchParams.get("source") ?? "";
  if (!SOURCES.has(source)) {
    return Response.json({ detail: "Pick where the export came from" }, { status: 400 });
  }
  if (Number(request.headers.get("content-length") ?? "0") > MAX_BYTES) {
    return Response.json({ detail: "export too large (max 20 MB)" }, { status: 413 });
  }
  const { getToken } = await auth();
  const token = await getToken();
  const body = await request.arrayBuffer();
  let upstream: Response;
  try {
    upstream = await fetch(`${API_ORIGIN}/api/tenant/first-party?source=${source}`, {
      method: "POST",
      headers: {
        "Content-Type": "text/csv",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body,
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
