import { AIOTile } from "@/components/aio-tile";
import type { AIOSummary, EngineMode, EngineModesPayload } from "@/lib/api";

// Each mode reads in its own colour: retrieve borrows the cobalt accent, recall
// a distinct violet, mixed a quiet teal. Standing is shown in the currency that
// fits the mode, so the two are never averaged into a false single number.
const MODE: Record<EngineMode["mode"], { color: string; soft: string; label: string }> = {
  retrieve: { color: "var(--accent)", soft: "var(--accent-soft)", label: "Retrieves" },
  recall: { color: "var(--mode-recall)", soft: "var(--mode-recall-soft)", label: "Recalls" },
  mixed: { color: "var(--mode-mixed)", soft: "var(--mode-mixed-soft)", label: "Mixed" },
};

function EngineCard({ e }: { e: EngineMode }) {
  const m = MODE[e.mode];
  const whole = Math.round(e.standing_value);
  return (
    <div className="card p-5">
      <span className="inline-flex items-center gap-1.5 text-[12px] text-[var(--text-2)]">
        <span className="h-1.5 w-1.5 rounded-full" style={{ background: m.color }} aria-hidden />
        {m.label}
      </span>
      <h3 className="mt-3 text-[16px]">{e.label}</h3>
      <p className="mt-1 min-h-[52px] text-xs leading-[1.45] text-[var(--text-2)]">{e.blurb}</p>
      <div className="mt-4 flex items-baseline justify-between border-t border-[var(--border)] pt-3">
        <span className="text-[28px] font-semibold tracking-[-0.025em] tabular-nums">
          {whole}
          <span className="text-[13px] text-[var(--text-3)]">%</span>
        </span>
        <span className="text-[11px] text-[var(--text-3)]">{e.standing_label}</span>
      </div>
      <p className="mt-2 text-[11.5px] leading-[1.4] text-[var(--text-2)]">
        <span className="font-semibold text-[var(--text)]">Play:</span> {e.play}
      </p>
    </div>
  );
}

function ModeColumn({
  kind,
  visibility,
  answers,
  brand,
}: {
  kind: "recall" | "retrieval";
  visibility: number;
  answers: number;
  brand: string;
}) {
  const recall = kind === "recall";
  const m = recall ? MODE.recall : MODE.retrieve;
  return (
    <div className="card p-5">
      <div className="mb-1 flex flex-col items-start gap-2">
        <span className="inline-flex items-center gap-1.5 text-[12px] text-[var(--text-2)]">
          <span className="h-1.5 w-1.5 rounded-full" style={{ background: m.color }} aria-hidden />
          {recall ? "Recall" : "Retrieval"}
        </span>
        <h3 className="text-[15px] font-semibold">
          {recall ? "Does the model already know you?" : "Do you appear when it searches?"}
        </h3>
      </div>
      <p className="mt-1.5 mb-3 text-xs leading-[1.5] text-[var(--text-2)]">
        {recall
          ? "Prompts the engine answers from what it already knows, without searching. This changes slowly and depends on how widely your brand is covered across the web."
          : "Prompts the engine answers by searching. It splits each prompt into sub-queries and picks sources for each. This changes quickly and responds to well-structured, citable pages."}
      </p>
      <div className="flex items-baseline gap-2">
        <span className="text-[30px] font-semibold tracking-[-0.025em] tabular-nums">
          {answers > 0 ? `${Math.round(visibility)}%` : "—"}
        </span>
        <span className="text-xs text-[var(--text-3)]">
          {recall
            ? `of memory answers name ${brand}`
            : `of live answers name ${brand}`}
          {answers > 0 ? ` · ${answers} measured` : ""}
        </span>
      </div>
    </div>
  );
}

export function EngineModesHero({
  data,
  aio,
}: {
  data: EngineModesPayload;
  aio: AIOSummary;
}) {
  const cols =
    data.engines.length >= 4
      ? "sm:grid-cols-2 lg:grid-cols-4"
      : data.engines.length === 3
        ? "sm:grid-cols-3"
        : "sm:grid-cols-2";
  return (
    <>
      <div className={`grid gap-3.5 ${cols}`}>
        {data.engines.map((e) => (
          <EngineCard key={e.surface} e={e} />
        ))}
      </div>

      {data.composite && (
        <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1 rounded-[var(--radius-lg)] border border-[var(--border)] px-5 py-4">
          <span className="text-[26px] font-semibold leading-none tracking-[-0.025em] tabular-nums">
            {data.composite.score}
          </span>
          <span className="text-xs text-[var(--text-2)]">
            Combined visibility across engines. The per-engine figures above are more useful for
            deciding what to do. Measured {data.composite.date}.
          </span>
        </div>
      )}

      <div className="mt-4 grid gap-3.5 lg:grid-cols-3">
        <ModeColumn
          kind="recall"
          visibility={data.modes.recall.visibility}
          answers={data.modes.recall.answers}
          brand={data.brand_name}
        />
        <ModeColumn
          kind="retrieval"
          visibility={data.modes.retrieval.visibility}
          answers={data.modes.retrieval.answers}
          brand={data.brand_name}
        />
        <AIOTile aio={aio} />
      </div>
    </>
  );
}
