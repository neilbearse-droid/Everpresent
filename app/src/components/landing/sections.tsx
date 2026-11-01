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

/** The differentiators, in the order they matter to someone deciding. Each one
 * is a capability in the product, not a promise. */
export const DIFFERENTIATORS: { title: string; body: string; proof: string }[] = [
  {
    title: "The answer your buyer actually gets",
    body:
      "Most tools ask a model over its API and call that visibility. We do that too, and then we open a clean, logged-out browser session on ChatGPT, Perplexity, Gemini and Copilot, and capture Google's AI Overviews and AI Mode from a real search. Same questions, same week, both ways, so you can see where the product differs from the API.",
    proof: "12 surfaces across 8 engines, each one labelled by how it was measured.",
  },
  {
    title: "The searches behind the answer",
    body:
      "When an engine searches before it answers, it splits your question into sub-searches. We record those, then re-run the important ones on their own to see who gets named for each. That tells you which specific sub-question you are losing, not just that your score moved.",
    proof: "Fan-out captured from ChatGPT, Gemini, Perplexity and Claude, with a step-by-step replay of a real answer.",
  },
  {
    title: "Evidence you can open, not a score",
    body:
      "Every answer is kept with its citations and the date it was given. A number on a dashboard links to the answers behind it. Rate changes come with a 95% range and a significance test, and when an engine changes under us we mark the break and withhold the verdict instead of reporting noise as progress.",
    proof: "Dated series breaks for the ChatGPT, AI Overviews and AI Mode changes of October 2026.",
  },
  {
    title: "Proof that your fix worked",
    body:
      "Log the change you shipped and the same questions are measured before and after it, on the engines that were stable across the window. If the window is confounded, the report says so rather than taking credit.",
    proof: "A before-and-after table in the client report, per logged fix.",
  },
  {
    title: "Mentions are the start; we follow it to revenue",
    body:
      "We pull AI-referred sessions and conversions from your GA4 alongside the mention rates, so a rise in visibility can be checked against leads. Where the engines' tracking is known to be broken, those days are marked as missing data and never estimated.",
    proof:
      "ChatGPT's links went untagged from 8 to 15 October 2026 and those visits landed in GA4 as Direct. Our charts grey those days out.",
  },
  {
    title: "Your own site, from the engines' side",
    body:
      "Which AI crawlers reached your site, which were blocked or served an error, which of your pages get cited, and whether engines run site: searches against you or against your rivals. The gaps become a short list of pages to write or fix, with a brief for the biggest ones.",
    proof: "Crawler access audit, cited-page inventory and a playbook with drafts.",
  },
  {
    title: "What the engines get wrong about you",
    body:
      "Visibility is not much use if the answer is inaccurate. We check the claims engines make against the facts you give us, and trace a wrong price or a retired product back to the page that most likely taught it.",
    proof: "Accuracy findings, each tied to a source page.",
  },
  {
    title: "Run on your terms",
    body:
      "A monthly spend cap per account, enforced before every call, so there is no surprise bill. You approve which engines run and whether answers may be processed by a model at all. Every change is in an audit log, and the raw answers stay yours.",
    proof: "Per-account caps, approved-engine list, audit log, raw answer retention.",
  },
];

export const STEPS: { title: string; body: string }[] = [
  {
    title: "We build your question set",
    body:
      "The questions your buyers actually type, by audience and by topic, with your brand, your competitors and your own pages registered. Branded questions are kept separate so they can't flatter the headline.",
  },
  {
    title: "It runs on a schedule",
    body:
      "Three times a week by default. Each run asks every question on every engine you've enabled, keeps the full answer, and notes the searches and citations behind it.",
  },
  {
    title: "You get a ranked list of things to do",
    body:
      "Where you're named, where a rival is named instead, which sources the engines trust, and the pages that would close the biggest gaps, with a draft brief for the top ones.",
  },
  {
    title: "Then we measure whether it worked",
    body:
      "Ship the change, log it, and the next runs tell you whether the mention rate moved on those questions, with the statistics stated and the engine changes accounted for.",
  },
];

export const FAQ: { q: string; a: string }[] = [
  {
    q: "How is this different from an AI visibility score?",
    a: "A score is one number with nothing underneath it. Here, every figure opens into the answers it came from, the searches the engine ran, and the sources it cited. If we can't tell whether a change is real, we say so.",
  },
  {
    q: "Which engines do you measure?",
    a: "ChatGPT, Google AI Overviews, Google AI Mode, Gemini, Claude, Perplexity, Microsoft Copilot and Meta AI. Each is measured over its API, as a logged-out browser session, or both, and every number says which.",
  },
  {
    q: "What do you need from us to start?",
    a: "Your brand name and aliases, your domains, the competitors you care about, and roughly 25 to 50 questions (we draft those with you). Read-only GA4 access is optional and only needed for the revenue side.",
  },
  {
    q: "What does it cost?",
    a: "Plans start at $149 a month; larger plans add questions, audiences, engines and locations. We confirm the number with you before you commit, and your account carries a hard monthly spend cap.",
  },
  {
    q: "Do you need logins to our accounts?",
    a: "No. We measure what a logged-out person sees, and we don't automate signed-in accounts. Where an engine can only be seen from a signed-in session, we take imported captures from a vendor that tracks it, and label them as imported.",
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
    <div className="max-w-[68ch]">
      <p className="ep-eyebrow">{eyebrow}</p>
      <h2 className="ep-h2 mt-3">{title}</h2>
      {children && (
        <div className="mt-4 text-[16px] leading-relaxed text-[var(--text-2)]">{children}</div>
      )}
    </div>
  );
}
