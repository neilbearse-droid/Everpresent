"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export function UploadLogs() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  async function onChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setBusy(true);
    setMsg(null);
    try {
      const res = await fetch("/dashboard/agents/upload", { method: "POST", body: file });
      const text = await res.text();
      if (!res.ok) {
        let detail = text;
        try {
          detail = JSON.parse(text).detail ?? text;
        } catch {}
        setMsg({ ok: false, text: detail || `Upload failed (HTTP ${res.status})` });
      } else {
        const d = JSON.parse(text);
        const overlap: string[] = d.overlap_days ?? [];
        setMsg({
          ok: true,
          text: `Read ${d.lines.toLocaleString()} lines: ${d.ai_hits.toLocaleString()} AI-bot hits kept, everything else discarded.${
            d.parsed === 0 ? " No line matched a known log format." : ""
          }${
            overlap.length
              ? ` Heads-up: ${overlap.length} of these days already had data, and uploads add up. If this file was uploaded before, those days are now counted twice.`
              : ""
          }`,
        });
        router.refresh();
      }
    } catch {
      setMsg({ ok: false, text: "Upload failed. Check your connection and try again." });
    } finally {
      setBusy(false);
      e.target.value = "";
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <label className="btn btn-primary w-fit cursor-pointer px-4 py-2 text-[12px]">
        {busy ? "Reading…" : "Upload access log"}
        <input
          type="file"
          accept=".log,.txt,.gz,.json,.jsonl,.csv,text/plain,application/gzip"
          className="hidden"
          disabled={busy}
          onChange={onChange}
        />
      </label>
      <p className="text-xs text-[var(--text-3)]">
        Apache/Nginx, Cloudflare Logpush, Vercel, CloudFront or JSON lines; .gz is fine (up to
        200 MB unzipped). Only AI-bot requests are kept; visitor data is discarded on read.
      </p>
      {msg && (
        <p className={`text-sm ${msg.ok ? "text-[var(--pos)]" : "text-[var(--neg)]"}`}>{msg.text}</p>
      )}
    </div>
  );
}
