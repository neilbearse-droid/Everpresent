import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";

const isProtectedRoute = createRouteMatcher(["/dashboard(.*)", "/admin(.*)"]);

// Read the Clerk keys at runtime so the real (host-provided) keys are used —
// not any placeholder baked into the image at build time. The publishable key
// is public by design; the secret key comes from the host environment.
export default clerkMiddleware(
  async (auth, req) => {
    if (isProtectedRoute(req)) {
      await auth.protect();
    }
  },
  {
    publishableKey: process.env.CLERK_PUBLISHABLE_KEY,
    secretKey: process.env.CLERK_SECRET_KEY,
  },
);

export const config = {
  // Report downloads (summary.pdf, *.csv) contain a dot, which the first
  // pattern skips — without middleware, auth() in that route throws a 500.
  matcher: ["/((?!_next|.*\\..*).*)", "/(api|trpc)(.*)", "/dashboard/reports/(.*)"],
};
