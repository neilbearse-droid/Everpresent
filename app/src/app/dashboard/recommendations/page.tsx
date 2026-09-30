import { apiFetch, type Me, type Recommendation } from "@/lib/api";
import { DashNav } from "@/components/dash-nav";
import { NoOrgNotice } from "@/components/no-org-notice";
import { setRecommendationStatus } from "./actions";

const BRANCH_LABELS: Record<Recommendation["branch"], string> = {
  web_search: "web-search gap",
  training: "training-data gap",
  aio: "AI Overview gap",
};
const BRANCH_STYLES: Record<Recommendation["branch"], string> = {
  web_search: "border border-[var(--border)] bg-[var(--surface)] text-[var(--accent)]",
  training: "border border-[var(--border)] bg-[var(--surface)] text-[var(--mode-recall)]",
  aio: "border border-[var(--border)] bg-[var(--surface)] text-[var(--pos)]",
};
const STATUS_STYLES: Record<Recommendation["status"], string> = {
  open: "text-[var(--warn-t)]",
  in_progress: "text-[var(--accent)]",
  done: "text-[var(--pos)]",
  dismissed: "text-[var(--text-3)]",
  resolved: "text-[var(--pos)]",
};
const NEXT_ACTIONS: Record<string, { to: Recommendation["status"]; label: string }[]> = {
  open: [
    { to: "in_progress", label: "Start" },
    { to: "dismissed", label: "Dismiss" },
  ],
  in_progress: [
    { to: "done", label: "Mark done" },
    { to: "open", label: "Back to open" },
  ],
  done: [{ to: "open", label: "Reopen" }],
  dismissed: [{ to: "open", label: "Reopen" }],
  resolved: [],
};

export default async function RecommendationsPage() {
  const [me, recs] = await Promise.all([
    apiFetch<Me>("/api/me"),
    apiFetch<Recommendation[]>("/api/tenant/recommendations"),
  ]);
  if (recs.status === 403) {
    return (
      <NoOrgNotice
        active="Recommendations"
        isSuperadmin={me.data?.is_superadmin}
        detail={recs.error}
      />
    );
  }
  const items = recs.data ?? [];
  const active = items.filter((r) => r.status === "open" || r.status === "in_progress");
  const closed = items.filter((r) => !active.includes(r));

  return (
    <main className="mx-auto max-w-5xl px-8 py-10">
      <DashNav active="Recommendations" isSuperadmin={me.data?.is_superadmin} />
      <p className="mb-6 text-sm text-[var(--text-2)]">
        Each visibility gap, mapped to a prescribed action: web-search gaps want citable
        published content, training gaps want brand-corpus presence, AI Overview gaps want
        presence in the sources Google's AIO cites.
      </p>

      {items.length === 0 && (
        <section className="card p-4">
          <p className="text-sm text-[var(--text-2)]">
            No recommendations yet. They appear once a run finds gaps.
          </p>
        </section>
      )}

      {[
        ["Needs action", active],
        ["Closed", closed],
      ].map(
        ([title, group]) =>
          (group as Recommendation[]).length > 0 && (
            <section key={title as string} className="mb-8">
              <h2 className="mb-3 text-sm font-medium text-[var(--text-2)]">{title as string}</h2>
              <ul className="space-y-3">
                {(group as Recommendation[]).map((rec) => (
                  <li
                    key={rec.id}
                    className="card p-4"
                  >
                    <div className="mb-2 flex flex-wrap items-center gap-3">
                      <span
                        className={`rounded px-2 py-0.5 text-xs font-medium ${BRANCH_STYLES[rec.branch]}`}
                      >
                        {BRANCH_LABELS[rec.branch]}
                      </span>
                      <span className={`text-xs font-medium ${STATUS_STYLES[rec.status]}`}>
                        {rec.status.replace("_", " ")}
                      </span>
                    </div>
                    <p className="text-sm leading-relaxed text-[var(--text)]">{rec.action_text}</p>
                    {NEXT_ACTIONS[rec.status].length > 0 && (
                      <div className="mt-3 flex gap-2">
                        {NEXT_ACTIONS[rec.status].map(({ to, label }) => (
                          <form
                            key={to}
                            action={setRecommendationStatus.bind(null, rec.id, to)}
                          >
                            <button className="rounded-md border border-[var(--border)] px-3 py-1.5 text-xs hover:bg-[var(--surface-2)]">
                              {label}
                            </button>
                          </form>
                        ))}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          ),
      )}
    </main>
  );
}
