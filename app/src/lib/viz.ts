// Categorical palette (dark-surface steps), validated with the dataviz
// six-checks script against the slate-900 card surface. Slot order is the
// CVD-safety mechanism — never reorder or cycle.
export const SERIES_COLORS = [
  "#3987e5", // 1 blue — always the brand
  "#199e70", // 2 aqua
  "#c98500", // 3 yellow
  "#008300", // 4 green
  "#9085e9", // 5 violet
  "#e66767", // 6 red
] as const;

export const DELTA_UP = "#199e70";
export const DELTA_DOWN = "#e66767";

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

export const LIKELIHOOD_LABELS: Record<string, string> = {
  very_likely: "very likely",
  likely: "likely",
  possible: "possible",
  unlikely: "unlikely",
};

// Ordinal blue steps (dark-mode band) for the web-search-likelihood chips —
// magnitude of one concept, so one hue stepped, not four hues.
export const LIKELIHOOD_COLORS: Record<string, string> = {
  very_likely: "#3987e5",
  likely: "#256abf",
  possible: "#1c5cab",
  unlikely: "#184f95",
};
