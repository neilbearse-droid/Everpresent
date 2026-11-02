import Link from "next/link";
import type { Metadata } from "next";
import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";
import { WaitlistForm } from "@/components/landing/waitlist-form";
import {
  ENGINES,
  FAQ,
  FIRST_MONTH,
  PROBLEMS,
  SectionHead,
  WHAT_YOU_GET,
} from "@/components/landing/sections";

const TITLE = "EverPresent: see what AI tells your buyers about you";
const DESCRIPTION =
  "Find out how often ChatGPT, Gemini, Perplexity and Google's AI recommend you, what they get wrong about you, and what to fix.";

export const metadata: Metadata = {
  // Absolute: the root layout's "%s · EverPresent" template would otherwise
  // append the brand a second time.
  title: { absolute: TITLE },
  description: DESCRIPTION,
  alternates: { canonical: "/" },
  openGraph: {
    title: TITLE,
    description: DESCRIPTION,
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
            <a href="#what" className="hover:text-white">
              What you get
            </a>
            <a href="#engines" className="hover:text-white">
              Engines
            </a>
            <a href="#agencies" className="hover:text-white">
              For agencies
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
              <h1 className="ep-h1 max-w-[20ch]">
                The shortlist gets made <span className="ep-key">before</span> anyone visits
                your site.
              </h1>
              <div className="mt-6 max-w-[58ch] space-y-4 text-[16.5px] leading-relaxed text-[var(--text-2)]">
                <p>
                  Someone with a budget asks ChatGPT, Gemini or Google&apos;s AI which companies
                  to look at, reads one paragraph, and walks away with three names. None of it
                  shows up in your analytics, and nobody tells you when it changes.
                </p>
                <p>
                  EverPresent asks those questions for you, week after week, on every engine
                  your buyers use. You see where you stand against each competitor, what the
                  engines get wrong about you, and which pages to fix first.
                </p>
              </div>

              <div className="mt-8 flex flex-wrap items-center gap-3">
                <a href="#waitlist" className="btn ep-cta px-5 py-3 text-[14px]">
                  Join the waitlist
                </a>
                <a href="#what" className="btn ep-outline px-5 py-3 text-[14px]">
                  What you get
                </a>
              </div>
              <p className="mt-4 text-[13px] text-[var(--text-3)]">
                We&apos;re onboarding a handful of accounts at a time. Plans start at $149 a
                month, each with a hard monthly ceiling.
              </p>

              <div className="mt-10 ep-divider pt-6">
                <p className="text-[12.5px] text-[var(--text-3)]">Engines we measure</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  {ENGINES.all.map((engine) => (
                    <span key={engine} className="ep-engine">
                      {engine}
                    </span>
                  ))}
                </div>
              </div>
            </div>

            <div id="waitlist" className="scroll-mt-24">
              <WaitlistForm source="landing-hero" />
            </div>
          </div>
        </section>

        {/* ---------- The problems a buyer already has ---------- */}
        <section className="border-y border-[var(--line)] bg-[#060606]">
          <div className="mx-auto grid w-full max-w-[1180px] grid-cols-1 gap-10 px-5 py-14 sm:px-8 md:grid-cols-3 md:gap-12">
            {PROBLEMS.map((item) => (
              <div key={item.title}>
                <h2 className="text-[18px] font-semibold leading-snug tracking-[-0.02em]">
                  {item.title}
                </h2>
                <p className="mt-3 text-[14.5px] leading-relaxed text-[var(--text-2)]">
                  {item.body}
                </p>
              </div>
            ))}
          </div>
        </section>

        {/* ---------- What you get ---------- */}
        <section id="what" className="scroll-mt-20">
          <div className="mx-auto w-full max-w-[1180px] px-5 py-16 sm:px-8 lg:py-24">
            <SectionHead title="What you get">
              <p>
                Numbers you can defend in a meeting, and a short list of things to do about them.
              </p>
            </SectionHead>

            <div className="mt-12 grid grid-cols-1 gap-px overflow-hidden rounded-[10px] border border-[var(--border)] bg-[var(--line)] md:grid-cols-2">
              {WHAT_YOU_GET.map((item, index) => (
                <div
                  key={item.title}
                  // An odd number of cards would leave a dead half-cell, so the
                  // last one takes the full width when the count is odd.
                  className={`bg-[#0a0a0a] p-6 sm:p-7 ${
                    index === WHAT_YOU_GET.length - 1 && WHAT_YOU_GET.length % 2 === 1
                      ? "md:col-span-2"
                      : ""
                  }`}
                >
                  <h3 className="text-[17.5px] font-semibold tracking-[-0.022em]">{item.title}</h3>
                  <p className="mt-2.5 text-[14.5px] leading-relaxed text-[var(--text-2)]">
                    {item.body}
                  </p>
                  <p className="mt-4 border-t border-[var(--line)] pt-3 text-[13px] leading-relaxed text-[var(--text-3)]">
                    {item.detail}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ---------- Engines ---------- */}
        <section id="engines" className="scroll-mt-20 border-y border-[var(--line)] bg-[#060606]">
          <div className="mx-auto w-full max-w-[1180px] px-5 py-16 sm:px-8 lg:py-20">
            <SectionHead title="The engines your buyers use">
              <p>
                ChatGPT, Google&apos;s AI Overviews and AI Mode, Gemini, Claude, Perplexity,
                Copilot and Meta AI. You choose which ones run for your account.
              </p>
            </SectionHead>

            <div className="mt-10 grid grid-cols-1 gap-6 md:grid-cols-2">
              <div className="card p-6">
                <h3 className="text-[16px] font-semibold tracking-[-0.02em]">Asked directly</h3>
                <p className="mt-2 text-[13.5px] leading-relaxed text-[var(--text-2)]">
                  Through each engine&apos;s own connection. Cheap enough to ask the same question
                  many times, which is how we tell a real change from one lucky answer.
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
                  Seen as a buyer sees it
                </h3>
                <p className="mt-2 text-[13.5px] leading-relaxed text-[var(--text-2)]">
                  A clean browser session in your market with no account history. This is the
                  answer your buyer gets, including the links beside it.
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
              We never automate a signed-in account to get these answers.
            </p>
          </div>
        </section>

        {/* ---------- For agencies ---------- */}
        <section id="agencies" className="scroll-mt-20">
          <div className="mx-auto w-full max-w-[1180px] px-5 py-16 sm:px-8 lg:py-20">
            <SectionHead title="If you run this for clients">
              <p>
                Each client gets their own login and a monthly report you can hand over as it is,
                with the margin of error on every number, so you can say what changed and why
                without hedging. You switch between clients without a separate login for each.
              </p>
            </SectionHead>
          </div>
        </section>

        {/* ---------- The first month ---------- */}
        <section id="how" className="scroll-mt-20 border-t border-[var(--line)] bg-[#060606]">
          <div className="mx-auto w-full max-w-[1180px] px-5 py-16 sm:px-8 lg:py-24">
            <SectionHead title="Your first month" />
            <ol className="mt-12 grid grid-cols-1 gap-px overflow-hidden rounded-[10px] border border-[var(--border)] bg-[var(--line)] md:grid-cols-2 lg:grid-cols-4">
              {FIRST_MONTH.map((step, index) => (
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
        <section id="faq" className="scroll-mt-20 border-t border-[var(--line)]">
          <div className="mx-auto grid w-full max-w-[1180px] grid-cols-1 gap-12 px-5 py-16 sm:px-8 lg:grid-cols-[0.8fr_1.2fr] lg:py-20">
            <SectionHead title="Questions we get asked" />
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
        <section className="border-t border-[var(--line)] bg-[#060606]">
          <div className="mx-auto grid w-full max-w-[1180px] grid-cols-1 items-start gap-12 px-5 py-16 sm:px-8 lg:grid-cols-[1fr_minmax(380px,0.9fr)] lg:gap-16 lg:py-24">
            <div>
              <h2 className="ep-h2 max-w-[24ch]">Find out what AI is telling your buyers.</h2>
              <p className="mt-5 max-w-[52ch] text-[16px] leading-relaxed text-[var(--text-2)]">
                Join the waitlist and we&apos;ll come back with the questions we&apos;d measure
                for your category, what the engines already say about you, and a price. If we
                look at it and think you don&apos;t need us yet, we&apos;ll say so.
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
