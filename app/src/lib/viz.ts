// Categorical palette — harmonised with the "Aperture" cobalt system. Refined,
// slightly desaturated hues that read cleanly on both the white (light) and
// lifted-black (dark) card surfaces. Slot order is the CVD-safety mechanism —
// never reorder or cycle.
export const SERIES_COLORS = [
  "#2f6bf0", // 1 cobalt — always the brand (matches --accent family)
  "#12a594", // 2 teal
  "#e0912f", // 3 amber
  "#3aa655", // 4 green
  "#8b7cf0", // 5 violet
  "#e8646a", // 6 coral
] as const;

export const DELTA_UP = "#16a34a";
export const DELTA_DOWN = "#e8646a";

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

// Ordinal cobalt steps for the web-search-likelihood chips — magnitude of one
// concept, so one hue stepped, not four hues. Harmonised with --accent.
export const LIKELIHOOD_COLORS: Record<string, string> = {
  very_likely: "#2f6bf0",
  likely: "#3f74d6",
  possible: "#3f66ad",
  unlikely: "#3a5788",
};
