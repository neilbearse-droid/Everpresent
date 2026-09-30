import { AIOTile } from "@/components/aio-tile";
import type { AIOSummary, EngineMode, EngineModesPayload } from "@/lib/api";

// Mode codes read like machine states. Colour is not used to tell modes apart:
// the single accent is reserved for the critical number, so modes are named.
const MODE_CODE: Record<EngineMode["mode"], string> = {
  retrieve: "MODE/RETRIEVE",
  recall: "MODE/RECALL",
  mixed: "MODE/MIXED",
};

function EngineCell({ e, index }: { e: EngineMode; index: number }) {
  const whole = Math.round(e.standing_value);
  return (
    <div className="flex flex-col">
      <div className="bp-label flex justify-between border-b-2 border-[var(--line)] px-3 py-1.5">
        <span>E{String(index + 1).padStart(2, "0")}</span>
        <span>{MODE_CODE[e.mode]}</span>
      </div>
      <div className="flex flex-1 flex-col p-3">
        <h3 className="bp-head text-[18px]">{e.label}</h3>
        <p className="mt-1 text-[12px] leading-snug text-[var(--text-2)]">{e.blurb}</p>
        <div className="mt-auto flex items-end justify-between gap-2 pt-4">
          <span className="bp-metric text-[44px]">
            {whole}
            <span className="text-[18px]">%</span>
          </span>
          <span className="bp-label pb-1.5 text-right">{e.standing_label}</span>
        </div>
      </div>
      <p className="border-t-2 border-[var(--line)] px-3 py-2 text-[11.5px] leading-snug">
        <span className="bp-label mr-1.5">Play</span>
        {e.play}
      </p>
    </div>
  );
}

/** One row of engine cells sharing blueprint grid lines. */
export function EngineStrip({ data }: { data: EngineModesPayload }) {
  const n = Math.min(Math.max(data.engines.length, 1), 4);
  const cols = { 1: "md:grid-cols-1", 2: "md:grid-cols-2", 3: "md:grid-cols-3", 4: "md:grid-cols-4" }[n];
  return (
    <div className={`blueprint grid-cols-1 ${cols}`}>
      {data.engines.map((e, i) => (
        <EngineCell key={e.surface} e={e} index={i} />
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
      <div className="bp-label mb-1">{recall ? "Recall / from memory" : "Retrieval / live search"}</div>
      <h3 className="bp-head text-[14px]">
        {recall ? "Does the model already know you?" : "Do you appear when it searches?"}
      </h3>
      <div className="mt-2 flex items-baseline gap-2">
        <span className="bp-metric text-[34px]">
          {answers > 0 ? `${Math.round(visibility)}%` : "N/A"}
        </span>
        <span className="text-[11.5px] leading-tight text-[var(--text-2)]">
          of {recall ? "memory" : "live"} answers name {brand}
          {answers > 0 ? ` · n=${answers}` : ""}
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
