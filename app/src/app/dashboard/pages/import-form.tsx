"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export function ImportFirstParty({ sources }: { sources: Record<string, string> }) {
  const router = useRouter();
  const [source, setSource] = useState("gsc");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  async function onChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setBusy(true);
    setMsg(null);
    try {
      const res = await fetch(`/dashboard/pages/import?source=${source}`, { method: "POST", body: file });
      const text = await res.text();
      let d: Record<string, unknown> = {};
      try {
        d = JSON.parse(text);
      } catch {}
      if (!res.ok) {
        setMsg({ ok: false, text: (d.detail as string) || text || `Import failed (HTTP ${res.status})` });
      } else {
        const metrics = (d.metrics as string[]) ?? [];
        setMsg({
          ok: true,
          text: `Imported ${Number(d.cells).toLocaleString()} values (${metrics.join(", ")}) across ${d.pages} pages${
            d.from ? `, ${d.from} to ${d.to}` : ""
          }. Re-importing the same dates replaces them.`,
        });
        router.refresh();
      }
    } catch {
      setMsg({ ok: false, text: "Import failed. Check your connection and try again." });
    } finally {
      setBusy(false);
      e.target.value = "";
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={source}
          onChange={(e) => setSource(e.target.value)}
          className="field min-w-0 px-2 py-1.5 text-[13px]"
          disabled={busy}
        >
          {Object.entries(sources).map(([k, label]) => (
            <option key={k} value={k}>
              {label}
            </option>
          ))}
        </select>
        <label className="btn btn-primary cursor-pointer px-4 py-2 text-[12.5px]">
          {busy ? "Importing…" : "Upload CSV export"}
          <input type="file" accept=".csv,.tsv,.txt,text/csv" className="hidden" disabled={busy} onChange={onChange} />
        </label>
      </div>
      <p className="text-xs text-[var(--text-3)]">
        Export the AI report as CSV and upload it here: Search Console (Performance → Generative
        AI), Bing Webmaster Tools (AI Performance), Merchant Center, Cloudflare AI Crawl Control
        or GA4. Columns are matched by name.
      </p>
      {msg && (
        <p className={`text-sm ${msg.ok ? "text-[var(--pos)]" : "text-[var(--neg)]"}`}>{msg.text}</p>
      )}
    </div>
  );
}
