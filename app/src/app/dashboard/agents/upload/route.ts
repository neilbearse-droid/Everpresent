import { auth } from "@clerk/nextjs/server";

const API_ORIGIN = process.env.API_ORIGIN ?? "http://localhost:8000";

/** Streams an access-log upload through to the API (the browser never holds
 * the API token, and large files never sit in a server-action body). */
export async function POST(request: Request) {
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
