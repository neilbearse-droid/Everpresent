// Categorical palette — deep, low-chroma hues that read as print-quality on
// white. The brand always takes the blue; competitors take the rest in
// alphabetical order. Slot order is fixed — never reorder or cycle.
export const SERIES_COLORS = [
  "#1d4ed8", // 1 blue — always the brand (matches --accent)
  "#0f766e", // 2 teal
  "#b45309", // 3 ochre
  "#6d28d9", // 4 violet
  "#be123c", // 5 crimson
  "#475569", // 6 slate
] as const;

export const DELTA_UP = "#0f7a45";
export const DELTA_DOWN = "#c62a22";

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

// Ordinal blue steps for the web-search-likelihood chips — magnitude of one
// concept, so one hue stepped, not four hues. Harmonised with --accent.
export const LIKELIHOOD_COLORS: Record<string, string> = {
  very_likely: "#1d4ed8",
  likely: "#3b63c9",
  possible: "#6b7fb3",
  unlikely: "#94a0bd",
};
