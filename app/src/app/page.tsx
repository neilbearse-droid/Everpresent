import Link from "next/link";
import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";
import { Wordmark } from "@/components/dash-nav";

const FEATURES = [
  {
    title: "Visibility by engine",
    body: "How often ChatGPT, Gemini, Claude, Perplexity and Copilot name your brand, tracked over time against the competitors you choose.",
  },
  {
    title: "The searches behind each answer",
    body: "The sub-queries each engine runs before it answers, whether you appear in the results for each one, and who does.",
  },
  {
    title: "Sources and fixes",
    body: "The pages the engines cite in your category, where your coverage is missing, and draft content to close each gap.",
  },
];

export default async function LandingPage() {
  // Signed-in visitors go straight to their dashboard.
  const { userId } = await auth();
  if (userId) redirect("/dashboard");

  return (
    <div className="min-h-screen bg-[var(--plane)]">
      <header className="border-b border-[var(--border)]">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-8">
          <Wordmark />
          <Link href="/sign-in" className="text-[13px] text-[var(--text-2)] hover:text-[var(--text)]">
            Sign in
          </Link>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-8">
        <section className="max-w-3xl py-24">
          <h1 className="text-5xl font-semibold leading-[1.05]">
            Know where your brand stands in AI answers.
          </h1>
          <p className="mt-6 max-w-2xl text-lg leading-relaxed text-[var(--text-2)]">
            EverPresent measures how AI assistants describe your category, whether they mention
            you, and which sources they rely on, so your team knows what to publish next.
          </p>
          <div className="mt-10 flex items-center gap-4">
            <Link href="/sign-in" className="btn btn-primary px-5 py-2.5">
              Sign in
            </Link>
            <span className="text-sm text-[var(--text-3)]">Access is by invitation.</span>
          </div>
        </section>

        <section className="grid border-t border-[var(--border)] md:grid-cols-3">
          {FEATURES.map((f, i) => (
            <div
              key={f.title}
              className={`py-10 md:pr-10 ${i > 0 ? "border-t border-[var(--border)] md:border-t-0 md:border-l md:pl-10" : ""}`}
            >
              <h2 className="text-[15px]">{f.title}</h2>
              <p className="mt-2 text-sm leading-relaxed text-[var(--text-2)]">{f.body}</p>
            </div>
          ))}
        </section>
      </main>

      <footer className="mt-16 border-t border-[var(--border)]">
        <div className="mx-auto max-w-6xl px-8 py-6 text-xs text-[var(--text-3)]">
          © {new Date().getFullYear()} EverPresent
        </div>
      </footer>
    </div>
  );
}
