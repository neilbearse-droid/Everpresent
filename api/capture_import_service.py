"""Import answers captured outside EverPresent (a vendor's panel, a
signed-in capture service), so they are measured exactly like our own.

EverPresent does not log in to consumer AI apps itself: automating signed-in
accounts breaks those services' terms, so signed-in answers come from a
vendor that holds that risk and hands us the captures. Each import becomes
one Run (trigger "import") whose results go through the normal processing:
mentions, citations, accuracy, sponsored units.

Format (JSON):

  {"source": "Vendor name",
   "captures": [{
      "surface": "chatgpt_web",           # an EverPresent surface code
      "query": "best domain registrar?",  # the prompt as asked
      "answer": "plain text",             # and/or "answer_html"
      "answer_html": "<div>…</div>",      # preferred: ads are cut from it
      "citations": [{"url": "https://…", "title": "…"}],
      "captured_at": "2026-10-01T14:03:00Z",
      "logged_in": true,
      "model": "gpt-…",                   # optional served model
      "persona": "generic",               # optional
      "location": ""                      # optional, e.g. "Austin, TX"
   }]}

Duplicates (same surface, query and answer text) already on file are
skipped, so re-sending a vendor export is safe."""

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator
from sqlmodel import Session, col, select

from api.models import (
    Citation,
    Result,
    ResultStatus,
    ResultVariant,
    Run,
    RunMode,
    RunStatus,
    SurfaceCode,
    Tenant,
    utcnow,
)
from api.storage import write_raw_envelope

MAX_CAPTURES = 5000
MAX_BYTES = 25 * 1024 * 1024
MAX_ANSWER_CHARS = 60_000


class CaptureCitation(BaseModel):
    url: str
    title: str = ""

    @field_validator("url")
    @classmethod
    def _http(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("citation url must start with http:// or https://")
        return v[:2000]


class Capture(BaseModel):
    surface: SurfaceCode
    query: str = Field(min_length=1, max_length=2000)
    answer: str = Field(default="", max_length=MAX_ANSWER_CHARS)
    answer_html: str = Field(default="", max_length=MAX_ANSWER_CHARS * 4)
    citations: list[CaptureCitation] = Field(default_factory=list, max_length=200)
    captured_at: datetime | None = None
    logged_in: bool | None = None
    model: str = Field(default="", max_length=200)
    persona: str = Field(default="generic", max_length=200)
    location: str = Field(default="", max_length=200)


class CaptureImport(BaseModel):
    source: str = Field(min_length=1, max_length=200)
    captures: list[Capture] = Field(min_length=1, max_length=MAX_CAPTURES)


def _as_utc(dt: datetime | None) -> datetime:
    if dt is None:
        return utcnow()
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def import_captures(session: Session, tenant: Tenant, payload: CaptureImport,
                    actor: str = "") -> dict[str, Any]:
    from api.processing_service import process_run
    from engine.retrievers.html_extract import extract_text_and_links

    assert tenant.id is not None
    now = utcnow()
    for c in payload.captures:
        # A little slack for clock skew between the vendor and us.
        if c.captured_at is not None and _as_utc(c.captured_at) > now + timedelta(minutes=10):
            raise ValueError(f"captured_at is in the future for “{c.query[:60]}”")
        if not (c.answer.strip() or c.answer_html.strip()):
            raise ValueError(f"empty answer for “{c.query[:60]}”")

    existing = {
        (str(s), q, h) for s, q, h in session.exec(
            select(col(Result.surface), col(Result.query_text), col(Result.response_hash))
            .where(Result.tenant_id == tenant.id)
        ).all()
    }
    run = Run(tenant_id=tenant.id, trigger="import", status=RunStatus.running,
              started_at=now, mode_set=["import"],
              surface_set=sorted({str(c.surface) for c in payload.captures}))
    session.add(run)
    session.flush()
    assert run.id is not None

    imported = skipped = citations = 0
    for index, c in enumerate(payload.captures):
        if c.answer_html.strip():
            text, links = extract_text_and_links(c.answer_html, ())
            text = text or c.answer
        else:
            text, links = c.answer.strip(), []
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        key = (str(c.surface), c.query, digest)
        if key in existing:
            skipped += 1
            continue
        existing.add(key)
        result = Result(
            run_id=run.id, tenant_id=tenant.id, query_text=c.query, persona_name=c.persona,
            surface=c.surface, mode=RunMode.B, variant=ResultVariant.search,
            status=ResultStatus.ok, location_label=c.location, response_hash=digest,
            served_model=c.model, logged_in=c.logged_in, created_at=_as_utc(c.captured_at),
        )
        result.raw_uri = write_raw_envelope(
            tenant.slug, run.id, f"import-{index:05d}",
            {"surface": str(c.surface), "mode": "import", "variant": "search",
             "source": payload.source, "query": c.query, "persona": c.persona,
             "model": c.model, "logged_in": c.logged_in,
             "response": {"html": c.answer_html} if c.answer_html else {},
             "parsed_text": text, "cost_usd": 0.0},
            session=session,
        )
        session.add(result)
        session.flush()
        assert result.id is not None
        seen: set[str] = set()
        for url in [*(link.url for link in links), *(cc.url for cc in c.citations)]:
            if url in seen:
                continue
            seen.add(url)
            domain = (urlparse(url).hostname or "").lower().removeprefix("www.")
            session.add(Citation(result_id=result.id, tenant_id=tenant.id, url=url,
                                 domain=domain))
            citations += 1
        imported += 1

    if not imported:
        # Nothing new: leave no empty run behind.
        session.rollback()
        return {"run_id": None, "imported": 0, "skipped_duplicates": skipped, "citations": 0}
    run.counts = {"imported": imported, "skipped_duplicates": skipped, "citations": citations,
                  "completed": imported, "source": payload.source, "by": actor}
    run.status = RunStatus.complete
    run.finished_at = utcnow()
    session.add(run)
    session.commit()
    run.counts = {**run.counts, **process_run(session, run)}
    session.add(run)
    session.commit()
    return {"run_id": run.id, "imported": imported, "skipped_duplicates": skipped,
            "citations": citations}
