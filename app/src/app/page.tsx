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
        <h1 className="bp-display max-w-[22ch]">
          See which brands AI recommends, and how often it&apos;s yours.
        </h1>
        <div className="mt-8 max-w-[60ch] space-y-4 text-[17px] leading-relaxed text-[var(--text-2)]">
          <p>
            Buyers now ask ChatGPT, Gemini, Claude, Perplexity, Copilot and Google&apos;s AI results
            which company to pick. EverPresent asks those engines the same questions every week,
            keeps every answer, and counts how often each one names you, who it names instead,
            and which web pages it took its information from.
          </p>
          <p>
            Most engines search the web before they answer. We record those searches, so you can
            see which of your pages an engine read and which it never reached. Where you&apos;re
            missing, you get a ranked list of what to publish or fix, with the evidence behind
            each suggestion.
          </p>
          <p>
            Built for agencies that run AI visibility for their clients: one login per client, a
            monthly report you can hand over, and every number shown with its margin of error.
          </p>
        </div>
        <div className="mt-10 flex flex-wrap items-center gap-4">
          <Link href="/sign-in" className="btn btn-primary px-5 py-2.5 text-[14px]">
            Sign in
          </Link>
          <span className="text-[13px] text-[var(--text-3)]">
            Access is by invitation while we&apos;re in beta.
          </span>
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
