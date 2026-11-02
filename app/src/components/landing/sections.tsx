import type { ReactNode } from "react";

/** The engines a measured answer can come from, grouped the way the product
 * measures them: over the provider's API, and as a logged-out person sees it. */
export const ENGINES = {
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

/** The same problem as a founder, a board member and a marketing lead each
 * meet it. Written to different lengths on purpose. */
export const PAIN: { title: string; body: string }[] = [
  {
    title: "Traffic is down and nobody can explain it",
    body:
      "Organic is off, pipeline looks about the same, and the quarterly review has no good answer for either. When the engine resolves the question on its own page there is no click to count, no keyword to point at, and nothing in your analytics that says it happened.",
  },
  {
    title: "Someone on the board is going to ask",
    body:
      "It usually arrives as “so what are we doing about AI search”. The honest answer at most companies is a few blog posts and a vendor call. It’s a bad question to get cold.",
  },
  {
    title: "You're paying for work nobody can check",
    body:
      "Agencies have been selling this for a year. Ask one what changed in the answers after six months and watch the room go quiet.",
  },
];

/** Four reasons to pick this over a scoreboard. Deliberately uneven. */
export const DIFFERENTIATORS: { title: string; body: string }[] = [
  {
    title: "Measured from the app your buyer opens",
    body:
      "Most tools query a model through its developer API and report whatever comes back. The app your customer uses answers differently, searches differently and puts different links beside the text. We run both, from a clean logged-out session in your market, and we label which is which so the two never get averaged together by accident.",
  },
  {
    title: "Every number opens",
    body:
      "Click a mention rate and you get the answers behind it, dated, with the brands named alongside you and the pages the engine cited. When the rate moves we say whether the move clears the noise. Engines changed how they answer four times this October, and on those dates we flag the break rather than drawing a line through it.",
  },
  {
    title: "The searches behind the answer",
    body:
      "An engine splits your buyer's question into its own searches before it writes anything. We capture those and re-run the ones that count, so you find out you’re losing on price comparisons, holding your own on integrations, and which page would close the first gap.",
  },
  {
    title: "Whether it worked",
    body:
      "Log the change you shipped and the same questions get asked either side of it, with the arithmetic shown. We pull your analytics in next to it, so the conversation with finance can be about sessions and leads.",
  },
];

export const STEPS: { title: string; body: string }[] = [
  {
    title: "We write the questions with you",
    body:
      "Mostly us asking what your buyers ask and writing down the wording they would use. Your brand, its aliases, your competitors and your key pages go in at the same time.",
  },
  {
    title: "It runs every week",
    body:
      "Every question, on every engine you’ve turned on, with the answers kept in full so you can read them yourself.",
  },
  {
    title: "You get a short list",
    body:
      "Five or six things worth doing, ordered by what they would move. Ship one and the following week tells you whether it landed.",
  },
];

export const FAQ: { q: string; a: string }[] = [
  {
    q: "How is this different from the other AI visibility tools?",
    a: "Most of them score you and stop there. We keep every answer, so when the number moves you have something to read. We also tell you when a change is too small to be real, which costs us the more exciting story about once a month.",
  },
  {
    q: "What do you need from us?",
    a: "Your brand and its aliases, your domains, the competitors that matter to you, and a session to draft the questions. Read-only access to your analytics if you want the revenue side. Nothing gets installed on your site.",
  },
  {
    q: "How soon do I have something worth showing the board?",
    a: "A baseline by engine and competitor in the first week. A trend needs about a month of runs behind it, because one run is a snapshot and four of them make a line.",
  },
  {
    q: "What does it cost?",
    a: "From $149 a month, going up with questions, audiences and engines. We’ll give you the number before you commit, and every account has a hard monthly ceiling, so a runaway bill isn’t possible.",
  },
];

export function SectionHead({
  eyebrow,
  title,
  children,
}: {
  eyebrow: string;
  title: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="max-w-[62ch]">
      <p className="ep-eyebrow">{eyebrow}</p>
      <h2 className="ep-h2 mt-3">{title}</h2>
      {children && (
        <div className="mt-4 text-[16px] leading-relaxed text-[var(--text-2)]">{children}</div>
      )}
    </div>
  );
}
