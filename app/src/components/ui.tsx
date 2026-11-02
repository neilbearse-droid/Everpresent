import Link from "next/link";
import type { ReactNode } from "react";

/* Small shared pieces that give text a hierarchy: links out of URLs, arrows
 * for movement, bold numbers, bullets with a lead-in, and an engine mark. */

const URL_RE = /(https?:\/\/[^\s)\]}>"']+)/g;

/** Shorten a URL for display: host plus a trimmed path, no scheme. */
export function shortUrl(url: string, max = 40): string {
  let s = url.replace(/^https?:\/\//, "").replace(/^www\./, "").replace(/\/$/, "");
  if (s.length > max) s = s.slice(0, max - 1) + "…";
  return s;
}

/** A link that opens in a new tab, shown short, marked as leaving the app. */
export function ExtLink({ href, children, className = "" }: { href: string; children?: ReactNode; className?: string }) {
  return (
    <a href={href} target="_blank" rel="noreferrer" className={`bp-link break-all ${className}`}>
      {children ?? shortUrl(href)}
      <span aria-hidden className="ml-0.5 text-[0.8em] no-underline">↗</span>
    </a>
  );
}

/** Render a sentence with every URL turned into an external link. */
export function Linkify({ text }: { text: string }) {
  const parts = text.split(URL_RE);
  return (
    <>
      {parts.map((part, i) =>
        /^https?:\/\//.test(part) ? (
          <ExtLink key={i} href={part.replace(/[.,;:]+$/, "")} />
        ) : (
          <Emph key={i} text={part} />
        ),
      )}
    </>
  );
}

const NUM_RE = /([+−-]?\d[\d,]*(?:\.\d+)?\s?(?:%|pts?|×)?)/g;

/** Bold the numbers in a sentence so the eye lands on them. */
export function Emph({ text }: { text: string }) {
  const parts = text.split(NUM_RE);
  return (
    <>
      {parts.map((p, i) =>
        i % 2 === 1 ? (
          <strong key={i} className="font-semibold tabular-nums text-[var(--text)]">
            {p}
          </strong>
        ) : (
          p
        ),
      )}
    </>
  );
}

/** ▲ +3 / ▼ 4 / – 0, in tabular figures. `value` is the signed change. */
export function Delta({ value, unit = "", digits = 0 }: { value: number | null | undefined; unit?: string; digits?: number }) {
  if (value === null || value === undefined) return <span className="text-[var(--text-3)]">–</span>;
  const n = Math.abs(value).toFixed(digits);
  if (Math.abs(value) < Math.pow(10, -digits) / 2) {
    return <span className="tabular-nums text-[var(--text-3)]">– 0{unit}</span>;
  }
  return value > 0 ? (
    <span className="font-semibold tabular-nums text-[var(--text)]">▲ +{n}{unit}</span>
  ) : (
    <span className="bp-neg tabular-nums">▼ {n}{unit}</span>
  );
}

export type Tone = "good" | "bad" | "neutral";

/** Bullet marker by tone: a loss, a win, or a plain point. */
export function Mark({ tone }: { tone: Tone }) {
  return (
    <span aria-hidden className={`mt-[2px] w-4 shrink-0 text-center text-[11px] ${tone === "bad" ? "font-bold" : tone === "good" ? "font-bold text-[var(--accent-2)]" : "text-[var(--text-3)]"}`}>
      {tone === "bad" ? "▼" : tone === "good" ? "▲" : "•"}
    </span>
  );
}

/** A bulleted list of short findings. Text before the first colon is the
 * lead-in and is set bold; URLs become links; numbers are emphasised. */
export function Bullets({ items, className = "" }: { items: { text: string; tone?: Tone; href?: string }[]; className?: string }) {
  return (
    <ul className={`space-y-2 ${className}`}>
      {items.map((it, i) => {
        const m = it.text.match(/^([^:]{3,40}):\s+(.*)$/s);
        return (
          <li key={i} className="flex gap-2 text-[13.5px] leading-snug text-[var(--text-2)]">
            <Mark tone={it.tone ?? "neutral"} />
            <span className="min-w-0">
              {m ? (
                <>
                  <span className="font-semibold text-[var(--text)]">{m[1]}: </span>
                  <Linkify text={m[2]} />
                </>
              ) : (
                <Linkify text={it.text} />
              )}
              {it.href && (
                <>
                  {" "}
                  <Link href={it.href} className="whitespace-nowrap text-[12px] font-medium text-[var(--accent-2)] hover:underline">
                    See →
                  </Link>
                </>
              )}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

/* Engine marks: a monogram tile in each engine's own hue, so a row of
 * engines reads at a glance. Hues are muted so they never compete with the
 * brand accent. Swap in licensed logos here if the assets are cleared. */
const ENGINE_MARKS: Record<string, { mono: string; bg: string; fg: string }> = {
  openai: { mono: "G", bg: "#dff5ec", fg: "#0f6e4f" }, // ChatGPT
  chatgpt: { mono: "G", bg: "#dff5ec", fg: "#0f6e4f" },
  claude: { mono: "C", bg: "#f6e6dc", fg: "#9a4a1f" },
  gemini: { mono: "✦", bg: "#e3ebfb", fg: "#2b4fb0" },
  perplexity: { mono: "P", bg: "#dcf0f3", fg: "#126a78" },
  copilot: { mono: "Co", bg: "#e6e9f7", fg: "#3a3f9e" },
  microsoft: { mono: "Co", bg: "#e6e9f7", fg: "#3a3f9e" },
  google: { mono: "G", bg: "#fde8e6", fg: "#b3261e" },
  meta: { mono: "M", bg: "#e3ecfc", fg: "#1b4fc2" },
};

/** Accepts a surface code ("copilot_web") or a label ("Microsoft Copilot"). */
function markFor(surface: string) {
  const s = surface.toLowerCase();
  const key = Object.keys(ENGINE_MARKS).find((k) => s.includes(k));
  return key ? ENGINE_MARKS[key] : { mono: surface.slice(0, 1).toUpperCase(), bg: "var(--plane-2)", fg: "var(--text-2)" };
}

/** A small tile that identifies an engine. `size` in px. */
export function EngineMark({ surface, size = 22 }: { surface: string; size?: number }) {
  const m = markFor(surface);
  return (
    <span
      aria-hidden
      className="inline-grid shrink-0 place-items-center rounded-[6px] font-bold leading-none"
      style={{ width: size, height: size, background: m.bg, color: m.fg, fontSize: Math.round(size * 0.5) }}
    >
      {m.mono}
    </span>
  );
}
