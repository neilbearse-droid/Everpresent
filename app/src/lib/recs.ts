// The words the product uses for a recommendation's area, rank and effort.
// Kept in one place so the Recommendations page, the overview and the
// Action Plan say the same thing. Mirrors api/impact.py.

export const AREAS: { key: string; label: string; asks: string }[] = [
  { key: "structure", label: "Website structure", asks: "Can AI reach and read your site?" },
  { key: "content", label: "Website content", asks: "Do your pages answer what buyers ask?" },
  { key: "accuracy", label: "Facts and accuracy", asks: "Is what AI says about you right?" },
  { key: "third_party", label: "Third-party mentions", asks: "Are you on the pages AI cites?" },
  { key: "reviews", label: "Reviews and ratings", asks: "What do review sites say about you?" },
  { key: "community", label: "Community and video", asks: "Are you in the conversations AI quotes?" },
  { key: "platforms", label: "Listings and platforms", asks: "Do stores and platforms list you correctly?" },
];

export const AREA_LABEL: Record<string, string> = {
  ...Object.fromEntries(AREAS.map((a) => [a.key, a.label])),
  setup: "Measurement",
};

/** Areas where someone else's page is the work: each play says what is realistic. */
export const OFF_SITE_AREAS = new Set(["third_party", "reviews", "community"]);

export const BAND_LABEL: Record<string, string> = {
  high: "High impact",
  medium: "Medium impact",
  low: "Low impact",
};
export const BAND_BARS: Record<string, number> = { high: 3, medium: 2, low: 1 };

export const CONTROL_LABEL: Record<string, string> = {
  own: "In your control",
  influence: "You can influence it",
  earn: "Has to be earned",
};
export const CONTROL_HELP: Record<string, string> = {
  own: "Your own site, profiles or facts: you decide.",
  influence: "Someone else's page, with a normal way in: a profile to claim, a thread to answer, a correction to request.",
  earn: "Someone else decides whether you appear at all.",
};

export const EFFORT_LABEL: Record<string, string> = {
  hours: "A few hours",
  days: "A few days",
  weeks: "Weeks",
};

export const SPEED_LABEL: Record<string, string> = {
  days: "Days, once recrawled",
  weeks: "Weeks",
  months: "Months",
  model: "The next model version",
};

export const EVIDENCE: Record<string, { label: string; help: string }> = {
  official: { label: "Official", help: "the platform's own documentation" },
  strong: { label: "Strong", help: "controlled studies or large datasets agree" },
  moderate: { label: "Moderate", help: "consistent studies, some vendor-run" },
  emerging: { label: "Emerging", help: "early or correlational evidence" },
};
