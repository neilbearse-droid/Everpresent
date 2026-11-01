import Link from "next/link";
import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";
import { Wordmark } from "@/components/dash-nav";

const PROBLEMS: { title: string; body: string }[] = [
  {
    title: "Your share of the answer",
    body:
      "How often AI names you when people ask about your category, which competitors it names " +
      "instead, and whether that is moving. One number per engine, with its margin of error, so " +
      "you know when a change is real and when it is noise.",
  },
  {
    title: "What AI gets wrong about you",
    body:
      "An old price, a plan you dropped, a policy you never had: AI repeats whatever page it " +
      "found. You see which claims are wrong, where they came from, and what to fix.",
  },
  {
    title: "What to do about it",
    body:
      "A short list of pages to write or fix, ranked by what the evidence says moves AI " +
      "answers, with a draft brief for each. No guessing at tags, markup or special files.",
  },
  {
    title: "Proof that it worked",
    body:
      "Every fix you ship is measured before and after, against the questions you left alone, " +
      "so the next report shows whether it moved anything.",
  },
];

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
          AI answers your buyers&apos; questions. See what it says about you.
        </h1>
        <p className="mt-8 max-w-[60ch] text-[17px] leading-relaxed text-[var(--text-2)]">
          A growing share of your customers ask ChatGPT, Gemini, Perplexity or Google&apos;s AI
          which company to go with, and the answer names someone. None of that shows up in your
          analytics, and nobody tells you when it changes.
        </p>

        <div className="mt-12 grid max-w-[64rem] gap-x-10 gap-y-8 sm:grid-cols-2">
          {PROBLEMS.map((p) => (
            <div key={p.title}>
              <h2 className="text-[15px] font-semibold text-[var(--text)]">{p.title}</h2>
              <p className="mt-2 text-[15px] leading-relaxed text-[var(--text-2)]">{p.body}</p>
            </div>
          ))}
        </div>

        <p className="mt-12 max-w-[60ch] text-[15px] leading-relaxed text-[var(--text-2)]">
          Running this for clients? Each client gets their own login and a monthly report you can
          hand over as it is, with numbers you can defend in the meeting.
        </p>

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
