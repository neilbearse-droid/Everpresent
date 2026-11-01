import type { MetadataRoute } from "next";

const SITE_URL = process.env.SITE_URL ?? "https://everpresent.io";

/** The landing page is the only public surface; the app itself is behind a
 * login and has nothing to index. */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [{ userAgent: "*", allow: "/", disallow: ["/dashboard", "/admin", "/sign-in"] }],
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
