import Link from "next/link";
import type { Metadata } from "next";
import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";
import { WaitlistForm } from "@/components/landing/waitlist-form";
import {
  DIFFERENTIATORS,
  ENGINES,
  FAQ,
  SectionHead,
  STEPS,
} from "@/components/landing/sections";

export const metadata: Metadata = {
  // Absolute: the root layout's "%s · EverPresent" template would otherwise
  // append the brand a second time.
  title: { absolute: "EverPresent — see what AI answers say about your brand" },
  description:
    "EverPresent measures how often ChatGPT, Google AI Overviews, Gemini, Claude, Perplexity, Copilot and Meta AI name your brand, keeps every answer as evidence, and turns the gaps into pages to fix.",
  alternates: { canonical: "/" },
  openGraph: {
    title: "EverPresent — see what AI answers say about your brand",
    description:
      "Measured answers from 12 surfaces across 8 AI engines, the searches behind them, and a ranked list of pages to fix.",
    url: "/",
    siteName: "EverPresent",
    type: "website",
  },
};

function Mark() {
  return (
    <span className="flex items-center gap-2.5">
      <span className="relative block h-5 w-5 rounded-[5px] bg-[var(--accent)]" aria-hidden>
        <span className="absolute inset-[5px] rounded-full border-2 border-black" />
      </span>
      <span className="text-[15.5px] font-semibold tracking-[-0.025em] text-white">
        EverPresent
      </span>
    </span>
  );
}

export default async function LandingPage() {
  // Signed-in visitors go straight to their dashboard.
  const { userId } = await auth();
  if (userId) redirect("/dashboard");

  const year = new Date().getFullYear();

  return (
    <div className="ep-landing min-h-screen">
      {/* ---------- Header ---------- */}
      <header className="sticky top-0 z-40 border-b border-[var(--line)] bg-black/85 backdrop-blur">
        <div className="mx-auto flex h-16 w-full max-w-[1180px] items-center justify-between px-5 sm:px-8">
          <Link href="/" aria-label="EverPresent home">
            <Mark />
          </Link>
          <nav className="hidden items-center gap-7 text-[13.5px] text-[var(--text-2)] md:flex">
            <a href="#different" className="hover:text-white">
              What&apos;s different
            </a>
            <a href="#engines" className="hover:text-white">
              Engines
            </a>
            <a href="#how" className="hover:text-white">
              How it works
            </a>
            <a href="#faq" className="hover:text-white">
              FAQ
            </a>
          </nav>
          <div className="flex items-center gap-2.5">
            <Link href="/sign-in" className="btn ep-outline px-3.5 py-1.5">
              Sign in
            </Link>
            <a href="#waitlist" className="btn ep-cta hidden px-3.5 py-1.5 sm:inline-flex">
              Join the waitlist
            </a>
          </div>
        </div>
      </header>

      <main>
        {/* ---------- Hero ---------- */}
        <section className="mx-auto w-full max-w-[1180px] px-5 pb-16 pt-14 sm:px-8 lg:pb-24 lg:pt-20">
          <div className="grid grid-cols-1 gap-12 lg:grid-cols-[1.05fr_minmax(380px,0.95fr)] lg:gap-16">
            <div>
              <p className="ep-eyebrow">Answer-engine visibility, measured properly</p>
              <h1 className="ep-h1 mt-4 max-w-[22ch]">
                See what AI answers say about your brand, and <span className="ep-key">why</span>.
              </h1>
              <div className="mt-6 max-w-[58ch] space-y-4 text-[16.5px] leading-relaxed text-[var(--text-2)]">
                <p>
                  Your buyers are asking ChatGPT, Google&apos;s AI Overviews, Gemini, Claude,
                  Perplexity, Copilot and Meta AI the questions they used to type into search.
                  EverPresent asks those same questions on a schedule and keeps every answer.
                </p>
                <p>
                  You see how often each engine names you, which competitor it names instead,
                  which pages it cites, and the searches it ran before it answered. The gaps
                  become a ranked list of pages to write or fix, and the next runs tell you
                  whether the fix worked.
                </p>
              </div>

              <div className="mt-8 flex flex-wrap items-center gap-3">
                <a href="#waitlist" className="btn ep-cta px-5 py-3 text-[14px]">
                  Join the waitlist
                </a>
                <a href="#different" className="btn ep-outline px-5 py-3 text-[14px]">
                  See what&apos;s different
                </a>
              </div>
              <p className="mt-4 text-[13px] text-[var(--text-3)]">
                Onboarding in small groups. Plans start at $149 a month, with a hard monthly
                spend cap on every account.
              </p>

              <div className="mt-10 ep-divider pt-6">
                <p className="bp-label">Measured engines</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  {[...ENGINES.api, "Copilot", "Google AI Overviews", "Google AI Mode"].map(
                    (engine) => (
                      <span key={engine} className="ep-engine">
                        {engine}
                      </span>
                    ),
                  )}
                </div>
              </div>
            </div>

            <div id="waitlist" className="scroll-mt-24">
              <WaitlistForm source="landing-hero" />
            </div>
          </div>
        </section>

        {/* ---------- Why now: two sourced facts ---------- */}
        <section className="border-y border-[var(--line)] bg-[#060606]">
          <div className="mx-auto grid w-full max-w-[1180px] grid-cols-1 gap-10 px-5 py-14 sm:px-8 md:grid-cols-2 md:gap-14">
            <div>
              <p className="ep-num">01</p>
              <p className="mt-3 text-[18px] font-semibold leading-snug tracking-[-0.02em]">
                Most AI answers are written from what the model already believes, not from a
                search it just ran.
              </p>
              <p className="mt-3 text-[14.5px] leading-relaxed text-[var(--text-2)]">
                Free, logged-out ChatGPT ran a web search on roughly one answer in seven across
                66.6 million answers (Ahrefs, October 2026). So your pages are one lever, and
                what the engines already hold about you is another. We measure both, and we
                report the share of answers where the engine chose to search at all.
              </p>
            </div>
            <div>
              <p className="ep-num">02</p>
              <p className="mt-3 text-[18px] font-semibold leading-snug tracking-[-0.02em]">
                Your analytics cannot see this channel on its own.
              </p>
              <p className="mt-3 text-[14.5px] leading-relaxed text-[var(--text-2)]">
                ChatGPT&apos;s outbound links went untagged from 8 to 15 October 2026, so a week
                of those visits was filed as Direct traffic and cannot be recovered (reported by
                Adobe and Profound). Answers that name you without linking to you never show up
                at all. The only way to know is to ask the engines and keep the answers.
              </p>
            </div>
          </div>
        </section>

        {/* ---------- Differentiators ---------- */}
        <section id="different" className="scroll-mt-20">
          <div className="mx-auto w-full max-w-[1180px] px-5 py-16 sm:px-8 lg:py-24">
            <SectionHead eyebrow="What's different" title="Built to stand up to a question">
              <p>
                Plenty of tools will tell you a number went up. The useful part is being able to
                say which answer, on which engine, to which question, and what to do about it.
                That is what the next eight points are for.
              </p>
            </SectionHead>

            <div className="mt-12 grid grid-cols-1 gap-px overflow-hidden rounded-[10px] border border-[var(--border)] bg-[var(--line)] md:grid-cols-2">
              {DIFFERENTIATORS.map((item, index) => (
                <div key={item.title} className="bg-[#0a0a0a] p-6 sm:p-7">
                  <p className="ep-num">{String(index + 1).padStart(2, "0")}</p>
                  <h3 className="mt-3 text-[17.5px] font-semibold tracking-[-0.022em]">
                    {item.title}
                  </h3>
                  <p className="mt-2.5 text-[14.5px] leading-relaxed text-[var(--text-2)]">
                    {item.body}
                  </p>
                  <p className="mt-4 border-t border-[var(--line)] pt-3 text-[13px] leading-relaxed text-[var(--text-3)]">
                    {item.proof}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ---------- Engines ---------- */}
        <section id="engines" className="scroll-mt-20 border-y border-[var(--line)] bg-[#060606]">
          <div className="mx-auto w-full max-w-[1180px] px-5 py-16 sm:px-8 lg:py-20">
            <SectionHead eyebrow="Coverage" title="Both ways of asking, labelled">
              <p>
                An engine&apos;s API and its app do not always answer the same way. We measure
                both and never mix them in one number without saying so.
              </p>
            </SectionHead>

            <div className="mt-10 grid grid-cols-1 gap-6 md:grid-cols-2">
              <div className="card p-6">
                <h3 className="text-[16px] font-semibold tracking-[-0.02em]">
                  Over the provider&apos;s API
                </h3>
                <p className="mt-2 text-[13.5px] leading-relaxed text-[var(--text-2)]">
                  Repeatable, cheap enough to run often, and the only way to ask the same
                  question many times and measure how much the answer varies.
                </p>
                <div className="mt-4 flex flex-wrap gap-2">
                  {ENGINES.api.map((engine) => (
                    <span key={engine} className="ep-engine">
                      {engine}
                    </span>
                  ))}
                </div>
              </div>
              <div className="card p-6">
                <h3 className="text-[16px] font-semibold tracking-[-0.02em]">
                  As a logged-out person sees it
                </h3>
                <p className="mt-2 text-[13.5px] leading-relaxed text-[var(--text-2)]">
                  A clean browser session, your market&apos;s location, no account history. This
                  is the answer your buyer gets, including the links beside it.
                </p>
                <div className="mt-4 flex flex-wrap gap-2">
                  {ENGINES.seen.map((engine) => (
                    <span key={engine} className="ep-engine">
                      {engine}
                    </span>
                  ))}
                </div>
              </div>
            </div>
            <p className="mt-5 text-[13px] leading-relaxed text-[var(--text-3)]">
              Where an engine can only be seen from a signed-in session, such as Meta&apos;s Muse
              agent, we take imported captures from a vendor that tracks it and label them as
              imported. We do not automate anyone&apos;s signed-in accounts.
            </p>
          </div>
        </section>

        {/* ---------- How it works ---------- */}
        <section id="how" className="scroll-mt-20">
          <div className="mx-auto w-full max-w-[1180px] px-5 py-16 sm:px-8 lg:py-24">
            <SectionHead eyebrow="How it works" title="Four steps, then it repeats" />
            <ol className="mt-12 grid grid-cols-1 gap-px overflow-hidden rounded-[10px] border border-[var(--border)] bg-[var(--line)] md:grid-cols-2 lg:grid-cols-4">
              {STEPS.map((step, index) => (
                <li key={step.title} className="bg-[#0a0a0a] p-6">
                  <p className="ep-num">Step {index + 1}</p>
                  <h3 className="mt-3 text-[16px] font-semibold tracking-[-0.022em]">
                    {step.title}
                  </h3>
                  <p className="mt-2.5 text-[14px] leading-relaxed text-[var(--text-2)]">
                    {step.body}
                  </p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        {/* ---------- FAQ ---------- */}
        <section id="faq" className="scroll-mt-20 border-t border-[var(--line)] bg-[#060606]">
          <div className="mx-auto grid w-full max-w-[1180px] grid-cols-1 gap-12 px-5 py-16 sm:px-8 lg:grid-cols-[0.8fr_1.2fr] lg:py-20">
            <SectionHead eyebrow="FAQ" title="The questions we get asked" />
            <dl className="divide-y divide-[var(--line)] border-t border-[var(--line)]">
              {FAQ.map((item) => (
                <div key={item.q} className="py-5">
                  <dt className="text-[15.5px] font-semibold tracking-[-0.02em]">{item.q}</dt>
                  <dd className="mt-2 text-[14.5px] leading-relaxed text-[var(--text-2)]">
                    {item.a}
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        </section>

        {/* ---------- Closing CTA ---------- */}
        <section className="border-t border-[var(--line)]">
          <div className="mx-auto grid w-full max-w-[1180px] grid-cols-1 items-start gap-12 px-5 py-16 sm:px-8 lg:grid-cols-[1fr_minmax(380px,0.9fr)] lg:gap-16 lg:py-24">
            <div>
              <h2 className="ep-h2 max-w-[24ch]">
                Find out what the engines are telling your buyers.
              </h2>
              <p className="mt-5 max-w-[52ch] text-[16px] leading-relaxed text-[var(--text-2)]">
                Join the waitlist and we&apos;ll come back with the questions we&apos;d measure
                for your category, what we can already see about your brand, and what it would
                cost to run properly.
              </p>
              <p className="mt-6 text-[13.5px] text-[var(--text-3)]">
                Prefer email?{" "}
                <a className="bp-link" href="mailto:hello@everpresent.io">
                  hello@everpresent.io
                </a>
              </p>
            </div>
            <WaitlistForm source="landing-footer" />
          </div>
        </section>
      </main>

      {/* ---------- Footer ---------- */}
      <footer className="border-t border-[var(--line)]">
        <div className="mx-auto flex w-full max-w-[1180px] flex-col gap-4 px-5 py-8 sm:flex-row sm:items-center sm:justify-between sm:px-8">
          <Mark />
          <div className="flex flex-wrap items-center gap-5 text-[12.5px] text-[var(--text-3)]">
            <a className="hover:text-white" href="mailto:hello@everpresent.io">
              hello@everpresent.io
            </a>
            <Link className="hover:text-white" href="/sign-in">
              Client sign in
            </Link>
            <span>© {year} EverPresent</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
