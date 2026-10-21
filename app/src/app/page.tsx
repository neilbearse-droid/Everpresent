import Link from "next/link";
import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";
import { Wordmark } from "@/components/dash-nav";

export default async function LandingPage() {
  // Signed-in visitors go straight to their dashboard.
  const { userId } = await auth();
  if (userId) redirect("/dashboard");

  return (
    <div className="flex min-h-screen flex-col bg-[var(--plane)]">
      <header className="mx-auto flex h-16 w-full max-w-[1200px] items-center justify-between px-6">
        <Wordmark />
        <Link href="/sign-in" className="btn btn-ghost px-3.5 py-1.5">
          Sign in
        </Link>
      </header>

      <main className="mx-auto w-full max-w-[1200px] flex-1 px-6 pb-20 pt-16 lg:pt-24">
        <h1 className="bp-display max-w-[20ch]">See how often AI answers name your brand.</h1>
        <div className="mt-8 max-w-[60ch] space-y-4 text-[17px] leading-relaxed text-[var(--text-2)]">
          <p>
            EverPresent puts the questions your buyers ask to ChatGPT, Gemini, Claude, Perplexity,
            Microsoft Copilot and Google&apos;s AI Overviews on a regular schedule, and keeps every
            answer. For each engine you see how often your brand is named, which competitors are
            named instead, and which web pages the engines cite as sources.
          </p>
          <p>
            It also records the web searches an engine runs before it answers and checks whether
            your brand turns up in them. The gaps become a list of pages to write or fix, with a
            draft brief for the biggest ones.
          </p>
        </div>
        <div className="mt-10 flex flex-wrap items-center gap-4">
          <Link href="/sign-in" className="btn btn-primary px-5 py-2.5 text-[14px]">
            Sign in
          </Link>
          <span className="text-[13px] text-[var(--text-3)]">Access is by invitation.</span>
        </div>
      </main>

      <footer className="border-t border-[var(--line)]">
        <div className="mx-auto max-w-[1200px] px-6 py-5 text-[12.5px] text-[var(--text-3)]">
          © {new Date().getFullYear()} EverPresent
        </div>
      </footer>
    </div>
  );
}
