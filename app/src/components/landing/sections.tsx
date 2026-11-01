import type { ReactNode } from "react";

/** The engines a measured answer can come from, grouped the way the product
 * asks them: directly, over the provider's own connection, and as a logged-out
 * buyer sees them in a browser. `all` is the list a visitor reads. */
export const ENGINES = {
  all: [
    "ChatGPT",
    "Google AI Overviews",
    "Google AI Mode",
    "Gemini",
    "Claude",
    "Perplexity",
    "Copilot",
    "Meta AI",
  ],
  api: ["ChatGPT", "Gemini", "Claude", "Perplexity", "Meta AI"],
  seen: [
    "ChatGPT (browser)",
    "Perplexity (browser)",
    "Gemini (browser)",
    "Copilot (browser)",
    "Google AI Overviews",
    "Google AI Mode",
  ],
};

/** The problems a buyer already has, whether or not they measure them. */
export const PROBLEMS: { title: string; body: string }[] = [
  {
    title: "Your analytics can't see it.",
    body:
      "When an AI answer sends a buyer to a competitor, nothing reaches your site and nothing is logged. When it sends them to you, the visit often arrives untagged. The channel stays invisible until you measure the answers themselves.",
  },
  {
    title: "The engines get things wrong about you.",
    body:
      "An old price, a plan you dropped, a policy you never had. The engines repeat whatever page taught them, and the buyer takes it as fact. Most companies find out when a customer repeats it back to them.",
  },
  {
    title: "It changes without notice.",
    body:
      "The engines swap models and change how they search several times a quarter. What was true about your visibility in September may not hold in October, and there is no announcement.",
  },
];

/** What a client gets, in the order a buyer would ask for it. `detail` is the
 * line under each card: where it shows up in the product. */
export const WHAT_YOU_GET: { title: string; body: string; detail: string }[] = [
  {
    title: "Your share of the answer",
    body:
      "How often AI names you when people ask about your category, which competitors it names instead, and whether that is moving. One number per engine, with its margin of error, so you know when a change is real and when it is noise.",
    detail: "Per engine and pooled, with the answers behind every number a click away.",
  },
  {
    title: "The answer your buyer actually gets",
    body:
      "An engine's app and its API don't always say the same thing. We ask both ways, from a clean logged-out session in your market, so you see the answer a real buyer sees, including the links beside it.",
    detail: "Eight engines, each labelled by how it was asked.",
  },
  {
    title: "Which questions you're losing",
    body:
      "When an engine searches before it answers, it splits your question into smaller ones. We show which of those name a competitor instead of you, so you know the exact question to win.",
    detail: "The searches behind each answer, kept with it.",
  },
  {
    title: "What AI gets wrong about you",
    body:
      "We check what the engines say against the facts you give us and trace each wrong claim to the page that most likely taught it, so you can fix the source.",
    detail: "Each wrong claim tied to a source page.",
  },
  {
    title: "What to do about it",
    body:
      "A short list of pages to write or fix, ranked by what the evidence says moves AI answers, with a draft brief for each. No guessing at tags, markup or special files.",
    detail: "Your team or your agency ships them as ordinary web pages.",
  },
  {
    title: "Proof that it worked",
    body:
      "Every fix you ship is measured before and after, against the questions you left alone, so the next report shows whether it moved anything. If an engine changed under us in that window, the report says so.",
    detail: "A before-and-after table in every report, per fix.",
  },
  {
    title: "Mentions that turn into visits",
    body:
      "Connect GA4 and AI-referred visits and conversions sit beside the mention rates, so you can tell whether being named more often brings anyone through the door. Days the engines' own tracking broke are marked as missing, never estimated.",
    detail: "Read-only GA4 access, optional.",
  },
  {
    title: "No surprise bill",
    body:
      "Every account has a hard monthly spend cap, enforced before each call. You choose which engines run. Every change is logged, and the raw answers stay yours to export.",
    detail: "Spend cap, engine list, audit log, export.",
  },
];

/** The first month, from the client's side. */
export const FIRST_MONTH: { title: string; body: string }[] = [
  {
    title: "You tell us who you are",
    body:
      "Your brand and its other names, your competitors, your market and your site. We draft the questions your buyers ask, usually 25 to 50, and you approve the list.",
  },
  {
    title: "The engines get asked",
    body:
      "Three times a week, on every engine you turned on. Within days you have a first picture: where you're named, where a competitor is named instead, and what's wrong in the answers.",
  },
  {
    title: "You fix what matters most",
    body:
      "A short list of pages to write or fix, in order, with a brief for each. Your team or your agency ships them as ordinary web pages.",
  },
  {
    title: "You see whether it moved",
    body:
      "The next report shows the before and after for each fix, with the margin of error stated, so you know what worked.",
  },
];

export const FAQ: { q: string; a: string }[] = [
  {
    q: "Isn't this just SEO?",
    a: "Partly. The pages AI engines cite are mostly the kind of page that ranks. The difference is that none of it shows in your rankings or your analytics, and the engines name competitors in places search never did. We measure the answers themselves.",
  },
  {
    q: "Which engines do you measure?",
    a: "ChatGPT, Google AI Overviews, Google AI Mode, Gemini, Claude, Perplexity, Microsoft Copilot and Meta AI. You choose which ones run for your account.",
  },
  {
    q: "How do I know a change is real?",
    a: "Every rate comes with its margin of error, and a change is only called real when the numbers support it. When an engine changes its model mid-month, the report marks the break instead of calling it progress.",
  },
  {
    q: "What do you need from us to start?",
    a: "Your brand name and its other names, your domains, the competitors you care about, and your market. We draft the questions with you. Read-only GA4 access is optional, and only needed if you want visits and leads beside the mention rates.",
  },
  {
    q: "What does it cost?",
    a: "It depends on how many questions, engines, audiences and markets you want measured. We confirm the price with you before you commit, and every account carries a hard monthly spend cap, so the bill is never a surprise.",
  },
  {
    q: "Do you need logins to our accounts?",
    a: "No. We ask the engines the way a logged-out buyer would, and we never automate anyone's signed-in account.",
  },
  {
    q: "Can I run this for my clients?",
    a: "Yes. Each client gets their own account, login and monthly report, and you switch between them without a separate login for each.",
  },
];

export function SectionHead({ title, children }: { title: ReactNode; children?: ReactNode }) {
  return (
    <div className="max-w-[68ch]">
      <h2 className="ep-h2">{title}</h2>
      {children && (
        <div className="mt-4 text-[16px] leading-relaxed text-[var(--text-2)]">{children}</div>
      )}
    </div>
  );
}
