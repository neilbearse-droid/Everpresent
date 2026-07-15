import type { Metadata } from "next";
import { ClerkProvider } from "@clerk/nextjs";
import "./globals.css";

export const metadata: Metadata = {
  title: "EverPresent",
  description: "Generative Engine Optimization — brand visibility in AI answers",
};

// Render everything dynamically so the Clerk publishable key is read from the
// runtime environment on every request. This keeps the container image
// secret-free — the real key is set as an env var on the host, never baked in
// at build time.
export const dynamic = "force-dynamic";

export default function RootLayout({ children }: { children: React.ReactNode }) {
  // Read the publishable key at runtime so managed platforms (Render) can set
  // it as an ordinary env var — no secret needs to be baked into the Docker
  // image at build time. Falls back to the build-time NEXT_PUBLIC_ value when
  // one was provided.
  const publishableKey =
    process.env.CLERK_PUBLISHABLE_KEY ?? process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;
  return (
    <ClerkProvider publishableKey={publishableKey}>
      <html lang="en">
        <body className="min-h-screen antialiased">{children}</body>
      </html>
    </ClerkProvider>
  );
}
