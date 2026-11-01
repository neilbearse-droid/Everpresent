import { auth } from "@clerk/nextjs/server";

const API_ORIGIN = process.env.API_ORIGIN ?? "http://localhost:8000";

/** Streams the waitlist CSV through the app so the browser never needs the
 * API bearer token (same pattern as the tenant report downloads). The API
 * rejects anyone who isn't a superadmin. */
export async function GET() {
  const { getToken } = await auth();
  const token = await getToken();
  let upstream: Response;
  try {
    upstream = await fetch(`${API_ORIGIN}/api/admin/waitlist.csv`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      cache: "no-store",
    });
  } catch {
    return new Response("The API is unreachable. Try again shortly.", { status: 502 });
  }
  if (!upstream.ok) {
    return new Response(await upstream.text(), { status: upstream.status });
  }
  return new Response(upstream.body, {
    headers: {
      "Content-Type": upstream.headers.get("content-type") ?? "text/csv",
      "Content-Disposition":
        upstream.headers.get("content-disposition") ??
        'attachment; filename="everpresent-waitlist.csv"',
    },
  });
}
