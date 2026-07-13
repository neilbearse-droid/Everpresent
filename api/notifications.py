"""Run-completion notifications (M5): the weekly report lands in the inbox
without anyone touching a terminal."""

import structlog
from sqlmodel import Session

from api.emailer import Attachment, send_email, smtp_configured
from api.models import Run, Tenant
from api.reports import build_results_csv, build_summary_pdf
from api.runs_service import month_spend_usd

log = structlog.get_logger()

CAP_ALERT_THRESHOLD = 0.8  # §9: alert at 80%


def notify_run_complete(session: Session, run: Run, tenant: Tenant) -> bool:
    if not tenant.notify_emails or not smtp_configured():
        return False
    assert tenant.id is not None and run.id is not None

    counts = run.counts or {}
    lines = [
        f"EverPresent run #{run.id} for {tenant.name} finished: {run.status}.",
        "",
        f"Calls: {counts.get('completed', 0)}/{counts.get('planned', 0)} completed, "
        f"{counts.get('failed', 0)} failed.",
        f"Mentions: {counts.get('mentions', 0)} · citations: {counts.get('citations', 0)} · "
        f"queries classified: {counts.get('classified_queries', 0)}.",
        f"Run cost: ${run.cost_usd:.4f}.",
    ]
    if run.error:
        lines += ["", f"Note: {run.error}"]

    month_spend = month_spend_usd(session, tenant.id)
    cap = tenant.monthly_spend_cap_usd
    if cap > 0 and month_spend >= CAP_ALERT_THRESHOLD * cap:
        lines += [
            "",
            f"SPEND ALERT: ${month_spend:.2f} of the ${cap:.2f} monthly cap used "
            f"({month_spend / cap:.0%}). Runs stop dispatching at the cap.",
        ]
    lines += ["", "The summary PDF and per-result CSV are attached."]

    try:
        attachments = [
            Attachment(
                filename=f"everpresent-{tenant.slug}-run-{run.id}.pdf",
                content=build_summary_pdf(session, tenant, run),
                mime_type="application/pdf",
            ),
            Attachment(
                filename=f"everpresent-{tenant.slug}-run-{run.id}-results.csv",
                content=build_results_csv(session, tenant.id, run.id).encode("utf-8"),
                mime_type="text/csv",
            ),
        ]
        return send_email(
            to=tenant.notify_emails,
            subject=f"[EverPresent] {tenant.name} — run #{run.id} {run.status}",
            body="\n".join(lines),
            attachments=attachments,
        )
    except Exception:  # noqa: BLE001 — notification failure must not fail the run
        log.exception("notify.failed", run_id=run.id, tenant=tenant.slug)
        return False
