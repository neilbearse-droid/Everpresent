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
    <div className="min-h-screen bg-[var(--plane)]">
      <header className="flex h-12 items-center justify-between bg-[var(--bar)] px-6">
        <Wordmark inverted />
        <Link
          href="/sign-in"
          className="font-mono text-[12px] font-bold uppercase text-[var(--bar-text)] hover:text-[var(--accent)]"
        >
          [Sign in]
        </Link>
      </header>

      <main className="mx-auto max-w-[1400px] px-6 py-10">
        <section className="blueprint grid-cols-1 lg:grid-cols-12">
          <div className="p-6 lg:col-span-8 lg:p-10">
            <div className="bp-label mb-6">AI answer visibility / measurement system</div>
            <h1 className="bp-display">
              Know where your brand stands in <span className="bp-alert">AI answers</span>.
            </h1>
            <p className="mt-8 max-w-2xl text-[16px] leading-relaxed text-[var(--text-2)]">
              EverPresent measures how AI assistants describe your category, whether they mention
              you, and which sources they rely on, so your team knows what to publish next.
            </p>
            <div className="mt-10 flex flex-wrap items-center gap-6">
              <Link href="/sign-in" className="btn btn-primary px-6 py-3 text-[13px]">
                Sign in →
              </Link>
              <span className="bp-label">Access by invitation</span>
            </div>
          </div>
          <div className="bp-stack grid-rows-[auto_repeat(6,1fr)] lg:col-span-4">
            <div className="bp-bar">
              <span>Engines monitored</span>
              <span>{String(ENGINES.length).padStart(2, "0")}</span>
            </div>
            {ENGINES.map((e, i) => (
              <div key={e} className="flex items-center justify-between px-4 py-3">
                <span className="bp-head text-[14px]">{e}</span>
                <span className="bp-label">CH{String(i + 1).padStart(2, "0")}</span>
              </div>
            ))}
          </div>
        </section>

        <section className="blueprint mt-8 grid-cols-1 md:grid-cols-3">
          {MODULES.map((m) => (
            <div key={m.code}>
              <div className="bp-bar">
                <span>{m.code}</span>
                <span>Module</span>
              </div>
              <div className="p-5">
                <h2 className="text-[18px]">{m.title}</h2>
                <p className="mt-2 text-sm leading-relaxed text-[var(--text-2)]">{m.body}</p>
              </div>
            </div>
          ))}
        </section>
      </main>

      <footer className="border-t-2 border-[var(--line)]">
        <div className="bp-label mx-auto max-w-[1400px] px-6 py-4">
          © {new Date().getFullYear()} EverPresent
        </div>
      </footer>
    </div>
  );
}
