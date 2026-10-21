"use client";

import { useEffect, useState, type CSSProperties } from "react";
import type { FanoutReplay, ReplayEngine, ReplaySub } from "@/lib/api";

// Four beats: the question, the split, the searches, the answer.
const STEPS = ["The question", "Split into searches", "Each search", "The answer"];
const STEP_MS = 2200;
const CARD_H = 64; // matches the cards' lg:h-[64px]
const GAP = 8;
const MAX_SUBS = 8;
const MIN_STAGE = 176;

function subBadge(s: ReplaySub, brand: string) {
  if (s.site) {
    const cls = s.site_kind === "you" ? "pill pill-good" : s.site_kind === "rival" ? "pill pill-bad" : "pill";
    const who = s.site_kind === "you" ? `${brand}'s site` : s.site_kind === "rival" ? `${s.site_name}'s site` : s.site;
    return <span className={cls}>Checked {who}</span>;
  }
  switch (s.status) {
    case "you":
      return <span className="pill pill-good">You appear</span>;
    case "rivals":
      return <span className="pill pill-bad">{s.winners.slice(0, 2).join(", ")} appear{s.winners.length === 1 ? "s" : ""}</span>;
    case "nobody":
      return <span className="pill">No brand listed</span>;
    default:
      return <span className="text-[11px] text-[var(--text-3)]">Not re-checked yet</span>;
  }
}

function lineColour(s: ReplaySub) {
  if (s.site_kind === "you" || (!s.site && s.status === "you")) return "var(--accent)";
  if (s.site_kind === "rival" || (!s.site && s.status === "rivals")) return "var(--text)";
  return "var(--border-strong)";
}

function caption(step: number, q: string, e: ReplayEngine, brand: string, subs: ReplaySub[]) {
  const sites = subs.filter((s) => s.site);
  const checked = subs.filter((s) => !s.site && s.status !== "unchecked");
  const yours = checked.filter((s) => s.status === "you").length;
  const rivalWins: Record<string, number> = {};
  checked.forEach((s) => s.status === "rivals" && s.winners.forEach((w) => (rivalWins[w] = (rivalWins[w] ?? 0) + 1)));
  const topRival = Object.entries(rivalWins).sort((a, b) => b[1] - a[1])[0];
  const rivalSites = sites.filter((s) => s.site_kind === "rival").map((s) => s.site_name);
  switch (step) {
    case 0:
      return `Someone asks ${e.label}: “${q}”`;
    case 1:
      return (
        `${e.label} breaks the question into ${e.subs.length} smaller ` +
        `search${e.subs.length === 1 ? "" : "es"} and reads what each one finds` +
        (sites.length ? `, ${sites.length === 1 ? "one" : sites.length} of them inside a single website.` : ".")
      );
    case 2:
      if (!checked.length && !sites.length)
        return "Each search returns its own results. We haven't re-run these searches yet, so we can't show who appears in each one.";
      return (
        "Each search returns its own results. " +
        (checked.length
          ? `When we re-ran them, you appeared in ${yours} of ${checked.length}` +
            (topRival ? `; ${topRival[0]} in ${topRival[1]}.` : ".")
          : "") +
        (rivalSites.length ? ` It also checked facts on ${[...new Set(rivalSites)].join(" and ")}'s site.` : "")
      );
    default: {
      const named = e.named
        ? `It writes the answer from what those searches found, and names ${brand}${e.rank ? ` #${e.rank}` : ""}.`
        : `It writes the answer from what those searches found. ${brand} isn't named` +
          (e.rivals_named.length ? `; ${e.rivals_named.slice(0, 3).join(", ")} ${e.rivals_named.length === 1 ? "is" : "are"}.` : ".");
      const cited = e.sources_total
        ? ` It cites ${e.sources_total} source${e.sources_total === 1 ? "" : "s"}${e.sources.some((s) => s.kind === "you") ? ", including your site" : ""}.`
        : "";
      const fix =
        !e.named && checked.some((s) => s.status === "rivals")
          ? " To change this answer, get into the searches where your rivals appear."
          : "";
      return named + cited + fix;
    }
  }
}

export function FanoutSimulator({ data }: { data: FanoutReplay }) {
  const [pi, setPi] = useState(0);
  const [ei, setEi] = useState(0);
  const [step, setStep] = useState(0);
  const [playing, setPlaying] = useState(false);

  const prompt = data.prompts[pi];
  const engine = prompt.engines[Math.min(ei, prompt.engines.length - 1)];
  const subs = engine.subs.slice(0, MAX_SUBS);
  const listH = Math.max(subs.length * (CARD_H + GAP) - GAP, 0);
  const stageH = Math.max(listH, MIN_STAGE);
  const top = (stageH - listH) / 2;
  const mid = stageH / 2;
  const ys = subs.map((_, i) => top + i * (CARD_H + GAP) + CARD_H / 2);

  useEffect(() => {
    if (!playing) return;
    if (step >= STEPS.length - 1) {
      setPlaying(false);
      return;
    }
    const t = setTimeout(() => setStep((s) => s + 1), step === 0 ? 900 : STEP_MS);
    return () => clearTimeout(t);
  }, [playing, step]);

  const choose = (p: number, e: number) => {
    setPi(p);
    setEi(e);
    setStep(0);
    setPlaying(false);
  };

  return (
    <section className="card mb-6 p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">Watch how an AI engine answers one question</h2>
          <p className="mt-1 max-w-2xl text-xs text-[var(--text-3)]">
            A replay of a real answer from your latest runs: the searches it ran, what we found when we
            re-ran them, and what it wrote.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            className="btn btn-primary px-3 text-[12.5px]"
            onClick={() => {
              if (step >= STEPS.length - 1) setStep(0);
              setPlaying(true);
            }}
            disabled={playing}
          >
            {playing ? "Playing…" : step >= STEPS.length - 1 ? "Replay" : "Play"}
          </button>
          <button
            className="btn btn-ghost px-3 text-[12.5px]"
            onClick={() => {
              setPlaying(false);
              setStep((s) => Math.min(s + 1, STEPS.length - 1));
            }}
            disabled={step >= STEPS.length - 1}
          >
            Step
          </button>
          <button
            className="btn btn-ghost px-3 text-[12.5px]"
            onClick={() => {
              setPlaying(false);
              setStep(0);
            }}
          >
            Reset
          </button>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <select
          aria-label="Question"
          className="max-w-full rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--surface)] px-2 py-1.5 text-sm"
          value={pi}
          onChange={(ev) => choose(Number(ev.target.value), 0)}
        >
          {data.prompts.map((p, i) => (
            <option key={p.query} value={i}>
              {p.query}
            </option>
          ))}
        </select>
        <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="Engine">
          {prompt.engines.map((e, i) => (
            <button
              key={e.surface}
              role="tab"
              aria-selected={e.surface === engine.surface}
              onClick={() => choose(pi, i)}
              className={`rounded-full border px-2.5 py-1 text-xs font-medium ${
                e.surface === engine.surface
                  ? "border-[var(--text)] bg-[var(--text)] text-[var(--ink-text)]"
                  : "border-[var(--border)] text-[var(--text-2)] hover:text-[var(--text)]"
              }`}
            >
              {e.label}
            </button>
          ))}
        </div>
      </div>

      {/* The stage: question → split → searches → answer. */}
      <div
        className="mt-5 grid grid-cols-1 gap-4 lg:min-h-[var(--stage)] lg:grid-cols-[minmax(170px,210px)_56px_minmax(0,1fr)_56px_minmax(220px,300px)] lg:gap-0"
        style={{ "--stage": `${stageH}px` } as CSSProperties}
      >
        {/* Engine box sits exactly on the fan's origin (the middle row). */}
        <div className="flex flex-col gap-3 lg:grid lg:min-h-[var(--stage)] lg:grid-rows-[1fr_auto_1fr] lg:gap-0">
          <div className="card-inset p-3 lg:mb-3 lg:self-end">
            <p className="text-xs font-medium text-[var(--text-3)]">Question</p>
            <p className="mt-1 text-sm font-medium">“{prompt.query}”</p>
          </div>
          <div
            className={`flex items-center gap-2 rounded-[var(--radius-sm)] border px-3 py-2 text-sm font-semibold transition-colors duration-500 motion-reduce:transition-none ${
              step >= 1 ? "border-[var(--text)] bg-[var(--text)] text-[var(--ink-text)]" : "border-[var(--border)]"
            }`}
          >
            {engine.label}
          </div>
        </div>

        <svg className="hidden lg:block" width="56" height={stageH} viewBox={`0 0 56 ${stageH}`} aria-hidden>
          {ys.map((y, i) => (
            <path
              key={i}
              d={`M0 ${mid} C 28 ${mid}, 28 ${y}, 56 ${y}`}
              fill="none"
              stroke="var(--border-strong)"
              strokeWidth="1.5"
              pathLength={1}
              strokeDasharray="1"
              strokeDashoffset={step >= 1 ? 0 : 1}
              style={{ transition: "stroke-dashoffset 600ms ease", transitionDelay: `${i * 110}ms` }}
              className="motion-reduce:!transition-none"
            />
          ))}
        </svg>

        <div className="flex flex-col justify-center lg:min-h-[var(--stage)]">
          <ul className="flex flex-col" style={{ gap: GAP }}>
            {subs.map((s, i) => (
              <li
                key={s.text}
                className={`flex min-h-[64px] flex-col items-start justify-center gap-1.5 rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--surface)] px-3 py-2 transition-all duration-500 motion-reduce:transition-none lg:h-[64px] lg:flex-row lg:items-center lg:justify-between lg:gap-3 lg:py-0 ${
                  step >= 1 ? "translate-x-0 opacity-100" : "-translate-x-2 opacity-0"
                }`}
                style={{ transitionDelay: `${i * 110}ms` }}
              >
                <span className="line-clamp-3 min-w-0 text-[13px] leading-snug lg:line-clamp-2">
                  {s.site ? (
                    <>
                      <span className="text-[var(--text-3)]">inside </span>
                      <span className="font-medium">{s.site}</span>
                      {s.looked_for ? <>: {s.looked_for}</> : null}
                    </>
                  ) : (
                    s.text
                  )}
                </span>
                <span
                  className={`shrink-0 transition-opacity duration-500 motion-reduce:transition-none ${step >= 2 ? "opacity-100" : "opacity-0"}`}
                  style={{ transitionDelay: `${i * 140}ms` }}
                >
                  {subBadge(s, data.brand_name)}
                </span>
              </li>
            ))}
          </ul>
          {engine.subs.length > MAX_SUBS && (
            <p className="mt-2 text-xs text-[var(--text-3)]">+{engine.subs.length - MAX_SUBS} more searches</p>
          )}
        </div>

        <svg className="hidden lg:block" width="56" height={stageH} viewBox={`0 0 56 ${stageH}`} aria-hidden>
          {ys.map((y, i) => (
            <path
              key={i}
              d={`M0 ${y} C 28 ${y}, 28 ${mid}, 56 ${mid}`}
              fill="none"
              stroke={lineColour(subs[i])}
              strokeWidth={lineColour(subs[i]) === "var(--border-strong)" ? 1.5 : 2}
              pathLength={1}
              strokeDasharray="1"
              strokeDashoffset={step >= 3 ? 0 : 1}
              style={{ transition: "stroke-dashoffset 600ms ease", transitionDelay: `${i * 90}ms` }}
              className="motion-reduce:!transition-none"
            />
          ))}
        </svg>

        <div className="flex flex-col justify-center">
          <div
            className={`rounded-[var(--radius-sm)] border p-3 transition-all duration-500 motion-reduce:transition-none ${
              step >= 3 ? "border-[var(--border-strong)] bg-[var(--surface)] opacity-100" : "border-dashed border-[var(--border)] opacity-60"
            }`}
          >
            <p className="text-xs font-medium text-[var(--text-3)]">{engine.label}&apos;s answer</p>
            {step < 3 ? (
              <p className="mt-2 text-sm text-[var(--text-3)]">Written from what the searches find.</p>
            ) : (
              <div className="mt-2 space-y-2">
                {engine.named ? (
                  <span className="pill pill-good">Names {data.brand_name}{engine.rank ? ` #${engine.rank}` : ""}</span>
                ) : (
                  <span className="pill pill-bad">{data.brand_name} not named</span>
                )}
                {engine.rivals_named.length > 0 && (
                  <p className="text-xs text-[var(--text-2)]">Also names {engine.rivals_named.join(", ")}</p>
                )}
                {engine.snippet && (
                  <p className="line-clamp-3 text-xs italic text-[var(--text-2)]">“{engine.snippet}”</p>
                )}
                {engine.sources.length > 0 && (
                  <div className="flex flex-wrap gap-1 pt-1">
                    {engine.sources.slice(0, 6).map((src) => (
                      <span
                        key={src.domain}
                        title={src.url}
                        className={`rounded px-1.5 py-0.5 text-[11px] ${
                          src.kind === "you"
                            ? "bg-[var(--accent-soft)] font-semibold text-[var(--accent-2)]"
                            : src.kind === "rival"
                              ? "bg-[var(--text)] text-[var(--ink-text)]"
                              : "bg-[var(--surface-2)] text-[var(--text-2)]"
                        }`}
                      >
                        {src.domain}
                      </span>
                    ))}
                    {engine.sources_total > 6 && (
                      <span className="text-[11px] text-[var(--text-3)]">+{engine.sources_total - 6}</span>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Narration, with the step markers. */}
      <div className="mt-5 flex flex-col gap-3 border-t border-[var(--line)] pt-4 md:flex-row md:items-start">
        <ol className="flex shrink-0 gap-1.5" aria-label="Steps">
          {STEPS.map((label, i) => (
            <li key={label}>
              <button
                onClick={() => {
                  setPlaying(false);
                  setStep(i);
                }}
                title={label}
                aria-current={i === step ? "step" : undefined}
                className={`flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-semibold ${
                  i === step
                    ? "bg-[var(--text)] text-[var(--ink-text)]"
                    : i < step
                      ? "border border-[var(--border-strong)] text-[var(--text)]"
                      : "border border-[var(--border)] text-[var(--text-3)]"
                }`}
              >
                {i + 1}
              </button>
            </li>
          ))}
        </ol>
        <p className="text-sm leading-relaxed text-[var(--text-2)]" aria-live="polite">
          <span className="font-semibold text-[var(--text)]">{STEPS[step]}. </span>
          {caption(step, prompt.query, engine, data.brand_name, subs)}
        </p>
      </div>
      <p className="mt-2 text-[11px] text-[var(--text-3)]">
        {engine.label}, {engine.date}. Sub-searches are the ones the engine reported; “appear” comes from re-running
        each one, and is only shown where we did.
      </p>
    </section>
  );
}
