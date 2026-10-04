import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  // Admin imports (vendor captures) post files through server actions.
  experimental: { serverActions: { bodySizeLimit: "25mb" } },
  async rewrites() {
    // In production Caddy routes /api to the FastAPI service; this rewrite
    // covers local dev (`next dev` + `uvicorn api.main:app`).
    const apiOrigin = process.env.API_ORIGIN ?? "http://localhost:8000";
    return [{ source: "/api/:path*", destination: `${apiOrigin}/api/:path*` }];
  },
};

export default nextConfig;
