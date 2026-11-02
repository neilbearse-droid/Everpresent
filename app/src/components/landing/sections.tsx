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

/** The problems a buyer already has, whether or not they measure them.
 * Different lengths on purpose. */
export const PROBLEMS: { title: string; body: string }[] = [
  {
    title: "Your analytics can't see it.",
    body:
      "When an AI answer sends a buyer to a competitor, nothing reaches your site and nothing gets logged. When it sends one to you, the visit often arrives untagged and lands in your reports as direct traffic. The channel stays invisible until somebody measures the answers themselves.",
  },
  {
    title: "The engines get things wrong about you.",
    body:
      "An old price, a plan you dropped, a policy you never had. The engines repeat whatever page taught them and the buyer takes it as fact. Most companies find out when a customer repeats it back to them.",
  },
  {
    title: "It changes without notice.",
    body:
      "Engines changed how they answer four times this October alone. What was true about your visibility in September might not hold now, and there's no announcement.",
  },
];

/** What a client gets, in the order a buyer would ask for it. `detail` is the
 * line under each card: where it shows up in the product. */
export const WHAT_YOU_GET: { title: string; body: string; detail: string }[] = [
  {
    title: "Your share of the answer",
    body:
      "How often AI names you when people ask about your category, which competitors it names instead, and whether that's moving. One number per engine with its margin of error, so you can tell a real change from noise.",
    detail: "Per engine and pooled, with the answers behind every number a click away.",
  },
  {
    title: "The answer your buyer actually gets",
    body:
      "An engine's app and its API don't always say the same thing. We ask both ways, from a clean session with no account signed in, in your market, so you see what a real buyer sees including the links beside the text.",
    detail: "Eight engines, each labelled by how it was asked.",
  },
  {
    title: "Which questions you're losing",
    body:
      "Before it answers, an engine splits your buyer's question into smaller ones of its own. We show which of those name a competitor instead of you, so you know the exact question to go and win.",
    detail: "The searches behind each answer, kept with it.",
  },
  {
    title: "What the engines get wrong",
    body:
      "We check what they say against the facts you give us, then trace each wrong claim back to the page that most likely taught it, so you can go and fix the source.",
    detail: "Each wrong claim tied to a source page.",
  },
  {
    title: "What to do, and whether it worked",
    body:
      "A short list of pages to write or fix, ranked by what the evidence says moves AI answers, with a draft brief for each. Ship one and the next report measures it against the questions you left alone. Connect GA4 and the visits and conversions sit beside the mention rates, so you can see whether being named more often brings anyone through the door.",
    detail: "Ordinary web pages. No guessing at tags, markup or special files.",
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
      "The next report shows the before and after for each fix with the margin of error stated, so you know what worked.",
  },
];

export const FAQ: { q: string; a: string }[] = [
  {
    q: "Isn't this just SEO?",
    a: "Partly. The pages AI engines cite are mostly the kind of page that ranks anyway. What's different is that none of it shows in your rankings or your analytics, and the engines name competitors in places search never did. We measure the answers themselves.",
  },
  {
    q: "How do I know a change is real?",
    a: "Every rate comes with its margin of error, and we only call a change real when the numbers support it. When an engine swaps its model mid-month, the report marks the break and says the window is confounded, which costs us the more exciting story about once a month.",
  },
  {
    q: "What do you need from us to start?",
    a: "Your brand name and its other names, your domains, the competitors you care about, and your market. We draft the questions with you, which takes about a session. Read-only GA4 access is optional and only needed if you want visits and leads beside the mention rates. Nothing gets installed on your site.",
  },
  {
    q: "How soon do I have something worth showing the board?",
    a: "A baseline by engine and competitor inside the first week. A trend needs about a month of runs behind it, because one run is a snapshot and a dozen make a line.",
  },
  {
    q: "What does it cost?",
    a: "From $149 a month, going up with the questions, engines, audiences and markets you want measured. We'll give you the number before you commit, and every account carries a hard monthly spend cap, enforced before each call, so the bill can't run away from you.",
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
