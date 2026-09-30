// Series palette — Blueprint. The brand is the ONE accent; competitors are
// black and greys, separated by dash pattern (SERIES_DASHES) rather than hue.
// Slot order is fixed — never reorder or cycle.
export const SERIES_COLORS = [
  "#ff5a1f", // 1 accent — always the brand
  "#0d0d0d", // 2
  "#0d0d0d", // 3
  "#5c5c56", // 4
  "#5c5c56", // 5
  "#9a9a92", // 6
] as const;

// strokeDasharray per slot, aligned with SERIES_COLORS.
export const SERIES_DASHES = ["", "", "6 3", "", "2 3", "8 3 2 3"] as const;

export const DELTA_UP = "#0d0d0d";
export const DELTA_DOWN = "#0d0d0d";

/** Stable entity→color map: brand takes slot 1, competitors take the
 * remaining slots in alphabetical order — color follows the entity, never its
 * rank, so filtering or re-sorting never repaints a series. Entities beyond
 * the palette are not given generated hues (they fold out of the trend). */
export function entityColors(
  brandName: string,
  competitorNames: string[],
): Map<string, string> {
  const map = new Map<string, string>();
  map.set(brandName, SERIES_COLORS[0]);
  [...competitorNames]
    .sort((a, b) => a.localeCompare(b))
    .slice(0, SERIES_COLORS.length - 1)
    .forEach((name, i) => map.set(name, SERIES_COLORS[i + 1]));
  return map;
}

// Human-readable names for measured surfaces. Falls back to the raw code for
// any surface without an entry.
export const SURFACE_LABELS: Record<string, string> = {
  openai_api: "ChatGPT (API)",
  perplexity_api: "Perplexity (API)",
  claude_api: "Claude (API)",
  gemini_api: "Gemini (API)",
  chatgpt_web: "ChatGPT (web)",
  perplexity_web: "Perplexity (web)",
  gemini_web: "Gemini (web)",
  copilot_web: "Microsoft Copilot",
  google_aio: "Google AI Overviews",
};

export function surfaceLabel(code: string): string {
  return SURFACE_LABELS[code] ?? code;
}

export const LIKELIHOOD_LABELS: Record<string, string> = {
  very_likely: "very likely",
  likely: "likely",
  possible: "possible",
  unlikely: "unlikely",
};

// Ordinal grey steps for the web-search-likelihood chips — magnitude of one
// concept, so one hue stepped, not four hues. Harmonised with --accent.
export const LIKELIHOOD_COLORS: Record<string, string> = {
  very_likely: "#0d0d0d",
  likely: "#3b3b37",
  possible: "#6b6b64",
  unlikely: "#9a9a92",
};
