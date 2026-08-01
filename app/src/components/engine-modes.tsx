import { AIOTile } from "@/components/aio-tile";
import type { AIOSummary, EngineMode, EngineModesPayload } from "@/lib/api";

// Each mode reads in its own colour: retrieve borrows the cobalt accent, recall
// a distinct violet, mixed a quiet teal. Standing is shown in the currency that
// fits the mode, so the two are never averaged into a false single number.
const MODE: Record<EngineMode["mode"], { color: string; soft: string; label: string; glyph: string }> = {
  retrieve: { color: "var(--accent)", soft: "var(--accent-soft)", label: "Retrieves", glyph: "▲" },
  recall: { color: "var(--mode-recall)", soft: "var(--mode-recall-soft)", label: "Recalls", glyph: "●" },
  mixed: { color: "var(--mode-mixed)", soft: "var(--mode-mixed-soft)", label: "Mixed", glyph: "◆" },
};

function EngineCard({ e }: { e: EngineMode }) {
  const m = MODE[e.mode];
  const whole = Math.round(e.standing_value);
  return (
    <div className="card card-hover relative overflow-hidden p-4">
      <span
        className="absolute inset-y-0 left-0 w-[3px]"
        style={{ background: m.color }}
        aria-hidden
      />
      <span
        className="font-display inline-flex items-center gap-1.5 rounded-full px-2 py-1 text-[10.5px] font-semibold uppercase tracking-[0.1em]"
        style={{ background: m.soft, color: m.color }}
      >
        <span aria-hidden>{m.glyph}</span> {m.label}
      </span>
      <h3 className="mt-2.5 text-[17px]">{e.label}</h3>
      <p className="mt-1 min-h-[52px] text-xs leading-[1.45] text-[var(--text-2)]">{e.blurb}</p>
      <div className="mt-2.5 flex items-baseline justify-between border-t border-[var(--border)] pt-2.5">
        <span className="font-display text-[22px] tracking-[-0.03em] tabular-nums">
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
      <div className="mb-1 flex items-center gap-2">
        <span
          className="font-display inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[10.5px] font-semibold uppercase tracking-[0.1em]"
          style={{ background: m.soft, color: m.color }}
        >
          <span aria-hidden>{m.glyph}</span> {recall ? "Recall" : "Retrieval"}
        </span>
        <h3 className="text-sm font-medium">
          {recall ? "Are you in the model's memory?" : "Do you win the live shards?"}
        </h3>
      </div>
      <p className="mt-1.5 mb-3 text-xs leading-[1.5] text-[var(--text-2)]">
        {recall
          ? "For prompts engines answer without searching, you're not ranking — you're already known or you're not. Moves slowly; shaped by durable corpus presence."
          : "For prompts engines search, the fan-out is the real contest surface. You compete page-by-page for each sub-query. Moves fast; shaped by citable, structured content."}
      </p>
      <div className="flex items-baseline gap-2">
        <span className="font-display text-[30px] tracking-[-0.035em] tabular-nums">
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
        <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1 rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--inset)] px-4 py-3">
          <span className="font-display text-[26px] leading-none tracking-[-0.03em] tabular-nums">
            {data.composite.score}
          </span>
          <span className="text-xs text-[var(--text-2)]">
            Blended visibility across engines — a convenience roll-up, not the story.
            Latest measurement · {data.composite.date}.
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
