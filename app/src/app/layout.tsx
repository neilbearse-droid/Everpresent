import type { Metadata } from "next";
import { ClerkProvider } from "@clerk/nextjs";
import "./globals.css";

export const metadata: Metadata = {
  title: "EverPresent",
  description: "Generative Engine Optimization — brand visibility in AI answers",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <ClerkProvider>
      <html lang="en">
        <body className="min-h-screen antialiased">{children}</body>
      </html>
    </ClerkProvider>
  );
}
