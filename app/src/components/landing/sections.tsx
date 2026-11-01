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

/** The three versions of the same problem, as a founder, a marketing lead and
 * a board member each run into it. Pain first; the product comes later. */
export const PAIN: { title: string; body: string }[] = [
  {
    title: "Traffic is down. Nobody can tell you why.",
    body:
      "The answer resolves the question on the page, so the buyer gets what they came for and never clicks. The decision still happens. The visit you used to count doesn't.",
  },
  {
    title: "The board will ask how you're positioned.",
    body:
      "There is a version of that meeting where you show a trend by engine, name who is being recommended instead of you, and say what you changed. Most companies are having the other version.",
  },
  {
    title: "The work is already being done. It isn't being measured.",
    body:
      "Agencies and in-house teams are shipping work in the name of AI search. Almost none of it is checked against the answers it was meant to change.",
  },
];

/** Four reasons to pick this over the tools being pitched alongside it. Each
 * one is a capability in the product, framed as what it gets the buyer. */
export const DIFFERENTIATORS: { title: string; body: string }[] = [
  {
    title: "We measure the answer your buyer gets",
    body:
      "Most tools query a model over its API and call the result visibility. An API behaves differently from the app your customer opens. We measure both, from a clean logged-out session in your market, and we never mix them in one number without saying so.",
  },
  {
    title: "Every figure opens",
    body:
      "Behind each number are the answers it came from: the question, the engine, the date, the brands named, the pages cited. Changes carry a range and a significance test. When an engine changes under us, we say so and withhold the verdict rather than sell you noise as progress.",
  },
  {
    title: "The reason, not just the result",
    body:
      "Before it answers, an engine breaks your buyer's question into searches of its own. We capture those and re-run the ones that matter. You find out which part of the question you lose, and which page would win it back.",
  },
  {
    title: "Proof, and then pipeline",
    body:
      "Log a change and the same questions are measured before and after it. Alongside that sit the sessions and conversions AI engines actually sent you, pulled from your own analytics. Visibility you can bank, rather than a score that went up.",
  },
];

export const STEPS: { title: string; body: string }[] = [
  {
    title: "We build the question set",
    body:
      "The questions your buyers ask, by audience and topic, with your brand, your competitors and your pages registered. It takes one working session.",
  },
  {
    title: "It runs every week",
    body:
      "Every question, on every engine you've enabled, with each answer kept in full. No tagging, no script on your site, nothing for your team to maintain.",
  },
  {
    title: "You get a short list, then proof",
    body:
      "Where you're named, who is named instead, and the few pages that would close the gap. Ship one, and the next runs tell you whether it moved.",
  },
];

export const FAQ: { q: string; a: string }[] = [
  {
    q: "How is this different from the tools being pitched to us?",
    a: "Most of them return a score. A score is one number with nothing underneath it, which makes it impossible to defend and impossible to act on. Here, every figure opens into the answers behind it, and anything we can't prove, we say we can't prove.",
  },
  {
    q: "What do you need from us?",
    a: "Your brand and its aliases, your domains, the competitors that matter, and roughly 25 to 50 buyer questions, which we draft with you. Read-only access to your analytics if you want the revenue side. Nothing goes on your site.",
  },
  {
    q: "How long until I have something worth presenting?",
    a: "The first run completes the week you start, and gives you a baseline by engine and competitor. A trend you'd put in front of a board takes about a month of runs behind it.",
  },
  {
    q: "What does it cost?",
    a: "Plans start at $149 a month and scale with questions, audiences and engines. We confirm the number before you commit, and every account carries a hard monthly cap, so the bill can't run away from you.",
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
