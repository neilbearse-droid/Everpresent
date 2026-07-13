import { auth } from "@clerk/nextjs/server";
import { notFound } from "next/navigation";

const API_ORIGIN = process.env.API_ORIGIN ?? "http://localhost:8000";
const ALLOWED = new Set(["results.csv", "visibility.csv", "summary.pdf"]);

/** Streams tenant report downloads through the app so the browser never
 * needs the API bearer token. */
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ file: string }> },
) {
  const { file } = await params;
  if (!ALLOWED.has(file)) notFound();
  const { getToken } = await auth();
  const token = await getToken();
  const upstream = await fetch(`${API_ORIGIN}/api/tenant/reports/${file}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    cache: "no-store",
  });
  if (!upstream.ok) {
    return new Response(await upstream.text(), { status: upstream.status });
  }
  return new Response(upstream.body, {
    headers: {
      "Content-Type": upstream.headers.get("content-type") ?? "application/octet-stream",
      "Content-Disposition":
        upstream.headers.get("content-disposition") ?? `attachment; filename="${file}"`,
    },
  });
}
