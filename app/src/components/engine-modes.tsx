import { AIOTile } from "@/components/aio-tile";
import type { AIOSummary, EngineMode, EngineModesPayload } from "@/lib/api";
import { EngineMark } from "@/components/ui";

// Modes are named in plain words; colour isn't used to tell them apart (the
// accent is reserved for the brand and good news).
const MODE_CODE: Record<EngineMode["mode"], string> = {
  retrieve: "Searches the web",
  recall: "Answers from memory",
  mixed: "Mixed",
};

function fact(e: EngineMode): string {
  const search = `Searches the web ${Math.round(e.search_rate)}%`;
  if (e.mode === "recall") return "Answers from memory";
  if (e.mode === "mixed") return `${search} · rest from memory`;
  return e.avg_fanout ? `${search} · ${e.avg_fanout.toFixed(1)} sub-searches` : search;
}

function EngineCell({ e }: { e: EngineMode }) {
  const whole = Math.round(e.standing_value);
  return (
    <div className="flex flex-col p-4">
      <div className="flex items-center gap-2.5">
        <EngineMark surface={e.surface} size={26} />
        <h3 className="bp-head min-w-0 flex-1 truncate text-[16px]">{e.label}</h3>
        <span className="chip shrink-0">{MODE_CODE[e.mode]}</span>
      </div>
      <div className="mt-4 flex items-end justify-between gap-2">
        <span className="bp-metric text-[40px]">
          {whole}
          <span className="text-[16px]">%</span>
        </span>
        <span className="bp-label pb-1.5 text-right">{e.standing_label}</span>
      </div>
      <p className="mt-2 text-[12px] tabular-nums text-[var(--text-3)]">{fact(e)}</p>
    </div>
  );
}

/** One row of engine cells sharing blueprint grid lines. */
export function EngineStrip({ data }: { data: EngineModesPayload }) {
  const n = Math.min(Math.max(data.engines.length, 1), 4);
  const cols = { 1: "md:grid-cols-1", 2: "md:grid-cols-2", 3: "md:grid-cols-3", 4: "md:grid-cols-4" }[n];
  return (
    <div className={`blueprint grid-cols-1 ${cols}`}>
      {data.engines.map((e) => (
        <EngineCell key={e.surface} e={e} />
      ))}
    </div>
  );
}

function ModeCell({
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
  return (
    <div className="p-3">
      <h3 className="bp-head text-[14px]">
        {recall ? "Answers from memory" : "Answers that searched the web"}
      </h3>
      <div className="mt-2 flex items-baseline gap-2">
        <span className="bp-metric text-[34px]">
          {answers > 0 ? `${Math.round(visibility)}%` : "—"}
        </span>
        <span className="text-[11.5px] leading-tight text-[var(--text-2)]">
          {answers > 0
            ? `of ${answers} ${answers === 1 ? "answer names" : "answers name"} ${brand}`
            : "No answers of this kind yet"}
        </span>
      </div>
    </div>
  );
}

/** The right-hand column beside the trend: recall, retrieval and Google AIO
 * stacked as cells. */
export function ModeStack({ data, aio }: { data: EngineModesPayload; aio: AIOSummary }) {
  return (
    <>
      <ModeCell
        kind="recall"
        visibility={data.modes.recall.visibility}
        answers={data.modes.recall.answers}
        brand={data.brand_name}
      />
      <ModeCell
        kind="retrieval"
        visibility={data.modes.retrieval.visibility}
        answers={data.modes.retrieval.answers}
        brand={data.brand_name}
      />
      <AIOTile aio={aio} />
    </>
  );
}
