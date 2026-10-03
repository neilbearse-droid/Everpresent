import Link from "next/link";
import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";
import { Wordmark } from "@/components/dash-nav";

const MODULES = [
  {
    code: "M01",
    title: "Visibility by engine",
    body: "How often ChatGPT, Gemini, Claude, Perplexity and Copilot name your brand, tracked over time against the competitors you choose.",
  },
  {
    code: "M02",
    title: "Search fan-out",
    body: "The sub-queries each engine runs before it answers, whether you appear in the results for each one, and who does.",
  },
  {
    code: "M03",
    title: "Sources and fixes",
    body: "The pages the engines cite in your category, where your coverage is missing, and draft content to close each gap.",
  },
];

const ENGINES = ["ChatGPT", "Gemini", "Claude", "Perplexity", "Copilot", "Google AI Overviews"];

export default async function LandingPage() {
  // Signed-in visitors go straight to their dashboard.
  const { userId } = await auth();
  if (userId) redirect("/dashboard");

  return (
    <div className="relative min-h-screen overflow-hidden bg-[var(--plane)]">
      {/* A soft warm glow behind the headline: the only decoration. */}
      <div
        aria-hidden
        className="pointer-events-none absolute -top-40 left-1/2 h-[560px] w-[900px] -translate-x-1/2 rounded-full opacity-90 blur-3xl"
        style={{ background: "radial-gradient(closest-side, var(--glow-1), transparent)" }}
      />
      <header className="relative mx-auto flex h-16 max-w-[1200px] items-center justify-between px-6">
        <Wordmark />
        <Link href="/sign-in" className="btn btn-ghost px-3.5 py-1.5">
          Sign in
        </Link>
      </header>

      <main className="relative mx-auto max-w-[1200px] px-6 pb-20 pt-16 lg:pt-24">
        <p className="eyebrow mb-6">AI answer visibility</p>
        <h1 className="bp-display max-w-[15ch]">
          Know where your brand stands in <em style={{ color: "var(--accent)" }}>AI answers</em>.
        </h1>
        <p className="mt-8 max-w-[56ch] text-[17px] leading-relaxed text-[var(--text-2)]">
          EverPresent measures how AI assistants describe your category, whether they mention you,
          and which sources they rely on, so your team knows exactly what to publish next.
        </p>
        <div className="mt-10 flex flex-wrap items-center gap-4">
          <Link href="/sign-in" className="btn btn-primary px-5 py-2.5 text-[14px]">
            Sign in <span aria-hidden>→</span>
          </Link>
          <span className="text-[13px] text-[var(--text-3)]">Access by invitation</span>
        </div>

        <div className="mt-16 flex flex-wrap items-center gap-2">
          <span className="mr-2 text-[13px] text-[var(--text-3)]">Measured across</span>
          {ENGINES.map((e) => (
            <span key={e} className="chip">
              {e}
            </span>
          ))}
        </div>

        <section className="mt-16 grid gap-4 md:grid-cols-3">
          {MODULES.map((m, i) => (
            <div key={m.code} className="card p-6">
              <span className="font-mono text-[12px] text-[var(--text-3)]">0{i + 1}</span>
              <h2 className="mt-6 text-[19px]">{m.title}</h2>
              <p className="mt-2 text-[14px] leading-relaxed text-[var(--text-2)]">{m.body}</p>
            </div>
          ))}
        </section>
      </main>

      <footer className="relative border-t border-[var(--line)]">
        <div className="mx-auto flex max-w-[1200px] justify-between px-6 py-5 text-[12.5px] text-[var(--text-3)]">
          <span>© {new Date().getFullYear()} EverPresent</span>
          <span>Measured, not guessed.</span>
        </div>
      </footer>
    </div>
  );
}
