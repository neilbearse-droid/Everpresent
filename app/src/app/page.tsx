import Link from "next/link";
import type { Metadata } from "next";
import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";
import { WaitlistForm } from "@/components/landing/waitlist-form";
import {
  DIFFERENTIATORS,
  ENGINES,
  FAQ,
  PAIN,
  SectionHead,
  STEPS,
} from "@/components/landing/sections";

export const metadata: Metadata = {
  // Absolute: the root layout's "%s · EverPresent" template would otherwise
  // append the brand a second time.
  title: { absolute: "EverPresent — know what AI answers tell your buyers" },
  description:
    "Buyers ask ChatGPT, Gemini and Google's AI Overviews who to consider. EverPresent shows you whether those answers name you, who they name instead, and what it takes to change them.",
  alternates: { canonical: "/" },
  openGraph: {
    title: "EverPresent — know what AI answers tell your buyers",
    description:
      "Whether AI answers name you, who they name instead, and what it takes to change them.",
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
            <a href="#shift" className="hover:text-white">
              What changed
            </a>
            <a href="#different" className="hover:text-white">
              Why EverPresent
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
              Request access
            </a>
          </div>
        </div>
      </header>

      <main>
        {/* ---------- Hero ---------- */}
        <section className="mx-auto w-full max-w-[1180px] px-5 pb-16 pt-14 sm:px-8 lg:pb-24 lg:pt-20">
          <div className="grid grid-cols-1 gap-12 lg:grid-cols-[1.05fr_minmax(380px,0.95fr)] lg:gap-16">
            <div>
              <h1 className="ep-h1 max-w-[19ch]">
                The shortlist is made <span className="ep-key">before</span> anyone visits
                your site.
              </h1>
              <div className="mt-7 max-w-[56ch] space-y-4 text-[16.5px] leading-relaxed text-[var(--text-2)]">
                <p>
                  Your buyers ask ChatGPT, Gemini, Perplexity and Google&apos;s AI Overviews who
                  to consider, and they act on the answer. Most of them never arrive on your
                  site to be counted.
                </p>
                <p>
                  EverPresent tells you whether those answers name you, who they name instead,
                  and what it takes to change them. Weekly, by engine, with the answers kept so
                  you can show your work.
                </p>
              </div>

              <div className="mt-9 flex flex-wrap items-center gap-3">
                <a href="#waitlist" className="btn ep-cta px-5 py-3 text-[14px]">
                  Request access
                </a>
                <a href="#different" className="btn ep-outline px-5 py-3 text-[14px]">
                  Why EverPresent
                </a>
              </div>
              <p className="mt-4 text-[13px] text-[var(--text-3)]">
                Onboarding in small groups. Plans start at $149 a month, capped so the bill
                can&apos;t surprise you.
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

        {/* ---------- The shift ---------- */}
        <section id="shift" className="scroll-mt-20 border-y border-[var(--line)] bg-[#060606]">
          <div className="mx-auto w-full max-w-[1180px] px-5 py-16 sm:px-8 lg:py-20">
            <SectionHead eyebrow="What changed" title="Buyers stopped clicking through to decide.">
              <p>
                They ask, they read one answer, and they turn up already holding a shortlist.
                The part of the journey you could measure moved somewhere you can&apos;t see.
              </p>
            </SectionHead>

            <div className="mt-12 grid grid-cols-1 gap-10 md:grid-cols-3 md:gap-8">
              {PAIN.map((item) => (
                <div key={item.title}>
                  <div className="h-px w-10 bg-[var(--accent)]" aria-hidden />
                  <h3 className="mt-5 text-[17px] font-semibold leading-snug tracking-[-0.022em]">
                    {item.title}
                  </h3>
                  <p className="mt-3 text-[14.5px] leading-relaxed text-[var(--text-2)]">
                    {item.body}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ---------- Why EverPresent ---------- */}
        <section id="different" className="scroll-mt-20">
          <div className="mx-auto w-full max-w-[1180px] px-5 py-16 sm:px-8 lg:py-24">
            <SectionHead eyebrow="Why EverPresent" title="A number is easy. Evidence is the hard part.">
              <p>
                You will be shown plenty of dashboards with a score on them. A score cannot be
                defended in a board meeting and cannot be acted on by a team. These four things
                can.
              </p>
            </SectionHead>

            <div className="mt-12 grid grid-cols-1 gap-px overflow-hidden rounded-[10px] border border-[var(--border)] bg-[var(--line)] md:grid-cols-2">
              {DIFFERENTIATORS.map((item, index) => (
                <div key={item.title} className="bg-[#0a0a0a] p-7 sm:p-8">
                  <p className="ep-num">{String(index + 1).padStart(2, "0")}</p>
                  <h3 className="mt-3 text-[18px] font-semibold tracking-[-0.022em]">
                    {item.title}
                  </h3>
                  <p className="mt-3 text-[14.5px] leading-relaxed text-[var(--text-2)]">
                    {item.body}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ---------- How it works ---------- */}
        <section id="how" className="scroll-mt-20 border-y border-[var(--line)] bg-[#060606]">
          <div className="mx-auto w-full max-w-[1180px] px-5 py-16 sm:px-8 lg:py-20">
            <SectionHead eyebrow="How it works" title="Three steps, then it repeats.">
              <p>
                Setup is a conversation, not an integration. Nothing is installed on your site
                and nothing lands on your team&apos;s backlog.
              </p>
            </SectionHead>
            <ol className="mt-12 grid grid-cols-1 gap-px overflow-hidden rounded-[10px] border border-[var(--border)] bg-[var(--line)] md:grid-cols-3">
              {STEPS.map((step, index) => (
                <li key={step.title} className="bg-[#0a0a0a] p-7">
                  <p className="ep-num">Step {index + 1}</p>
                  <h3 className="mt-3 text-[17px] font-semibold tracking-[-0.022em]">
                    {step.title}
                  </h3>
                  <p className="mt-3 text-[14.5px] leading-relaxed text-[var(--text-2)]">
                    {step.body}
                  </p>
                </li>
              ))}
            </ol>

            <div className="mt-10 ep-divider pt-7">
              <p className="bp-label">
                Measured over each provider&apos;s API and from a clean logged-out session, so
                you see what your buyer sees
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                {ENGINES.seen.map((engine) => (
                  <span key={engine} className="ep-engine">
                    {engine}
                  </span>
                ))}
              </div>
            </div>
          </div>
        </section>

        {/* ---------- FAQ ---------- */}
        <section id="faq" className="scroll-mt-20">
          <div className="mx-auto grid w-full max-w-[1180px] grid-cols-1 gap-12 px-5 py-16 sm:px-8 lg:grid-cols-[0.8fr_1.2fr] lg:py-20">
            <SectionHead eyebrow="FAQ" title="Before you ask" />
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

        {/* ---------- Closing ---------- */}
        <section className="border-t border-[var(--line)] bg-[#060606]">
          <div className="mx-auto grid w-full max-w-[1180px] grid-cols-1 items-start gap-12 px-5 py-16 sm:px-8 lg:grid-cols-[1fr_minmax(380px,0.9fr)] lg:gap-16 lg:py-24">
            <div>
              <h2 className="ep-h2 max-w-[20ch]">Find out what they already say about you.</h2>
              <p className="mt-5 max-w-[50ch] text-[16px] leading-relaxed text-[var(--text-2)]">
                Request access and we&apos;ll come back with the questions we would measure for
                your category, what the engines say about you today, and what it costs to run
                properly. No deck.
              </p>
              <p className="mt-6 text-[13.5px] text-[var(--text-3)]">
                Or write to{" "}
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
