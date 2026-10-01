"""Fan-out shards (§FANOUT_SCORECARD M25b): harvest the sub-queries a run's
engines fanned out into, pick which to re-probe under the plan's caps, and turn
a re-probe answer into per-shard presence.

Harvest and scoring are pure reads/writes over this run; the provider calls
live in worker.jobs.run_fanout_reprobe. Presence is only ever claimed from a
re-probe of the shard itself — the parent answer's citations are answer-level
and say nothing about any one shard (§2)."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, timedelta

from sqlmodel import Session, select

from api.models import FanoutShard, Query, Result, Run, utcnow
from engine.processing.citations import domain_is_owned
from engine.processing.mentions import detect_mentions

# Priority order for the scorecard (§6). Unresolved shards carry "" — no claim.
PRIORITY_RANK = {"high": 0, "med": 1, "low": 2, "": 3}

# When a shard was issued by several engines, re-probe it once on the cheapest
# issuing surface: an OpenAI probe costs ~$0.02–0.07, a Gemini one ~$0.14
# because grounding bills per sub-query (DECISIONS.md M25b).
REPROBE_SURFACE_ORDER = ["openai_api", "gemini_api"]


def shard_norm(text: str) -> str:
    """Lowercase + collapsed whitespace: the dedup and cross-run join key."""
    return " ".join(str(text).lower().split())


def names_present(text_low: str, tokens: set[str]) -> bool:
    """Whitespace-delimited containment — a token counts only as a standalone
    word (so 'wix' doesn't fire inside 'wixel')."""
    padded = f" {text_low} "
    return any(f" {t} " in padded for t in tokens if t)


def shard_priority(brand_present: bool | None, winners: list[str]) -> str:
    """§6, settled for two fan-out engines (DECISIONS.md M25b): HIGH = you're
    absent and a competitor won the shard; MED = you're absent, nobody tracked
    won; LOW = you're present. Reach orders shards within a band rather than
    gating HIGH — with only Gemini and OpenAI exposing fan-out, an exact
    shard match across both is rare, so a reach ≥ 2 gate would leave HIGH
    empty. Unresolved shards get no priority."""
    if brand_present is None:
        return ""
    if brand_present:
        return "low"
    return "high" if winners else "med"


def _as_utc(stamp):
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)


def harvest_shards(
    session: Session, run: Run, search_results: list[Result], *, ttl_days: int
) -> int:
    """Upsert this run's FanoutShard rows from its search results' fan-out.
    Competitive prompts only (branded probes live in the Brand layer). A shard
    that was re-probed within `ttl_days` — in this run or an earlier one —
    carries its presence forward instead of being re-bought. Idempotent:
    reprocessing updates rows in place and drops shards no longer observed."""
    assert run.id is not None
    branded = {
        q.text
        for q in session.exec(
            select(Query).where(
                Query.tenant_id == run.tenant_id, Query.branded == True  # noqa: E712
            )
        ).all()
    }

    observed: dict[tuple[str, str], dict] = {}
    for r in search_results:
        if r.query_text in branded:
            continue
        parent_norm = shard_norm(r.query_text)
        for sub in r.fanout_queries or []:
            text = str(sub).strip()
            norm = shard_norm(text)
            if not norm or norm == parent_norm:
                continue
            entry = observed.setdefault(
                (r.query_text, norm), {"text": text, "surfaces": set(), "forms": {}}
            )
            entry["surfaces"].add(str(r.surface))
            entry["forms"][text] = entry["forms"].get(text, 0) + 1

    # Display wording: the most common form, ties to the cleanest (single-
    # spaced, lowercase) — never "whichever row the database returned first",
    # which differs between Postgres and SQLite and between runs.
    for entry in observed.values():
        entry["text"] = min(
            entry["forms"],
            key=lambda t: (
                -entry["forms"][t], t != " ".join(t.split()), t != t.lower(), t,
            ),
        )

    existing = {
        (row.parent_query_text, row.shard_norm): row
        for row in session.exec(
            select(FanoutShard).where(FanoutShard.run_id == run.id)
        ).all()
    }
    for key, row in existing.items():
        if key not in observed:
            session.delete(row)

    # Fresh re-probes from earlier runs, newest first per key.
    cutoff = utcnow() - timedelta(days=ttl_days)
    fresh: dict[tuple[str, str], FanoutShard] = {}
    if ttl_days > 0 and observed:
        for row in session.exec(
            select(FanoutShard)
            .where(
                FanoutShard.tenant_id == run.tenant_id,
                FanoutShard.run_id != run.id,
                FanoutShard.source == "reprobed",
            )
            .order_by(FanoutShard.id.desc())  # pyright: ignore[reportAttributeAccessIssue, reportOptionalMemberAccess]
        ).all():
            key = (row.parent_query_text, row.shard_norm)
            if key in fresh or key not in observed or row.probed_at is None:
                continue
            if _as_utc(row.probed_at) >= cutoff:
                fresh[key] = row

    for key, entry in observed.items():
        surfaces = sorted(entry["surfaces"])
        row = existing.get(key)
        if row is None:
            row = FanoutShard(
                tenant_id=run.tenant_id,
                run_id=run.id,
                parent_query_text=key[0],
                shard_text=entry["text"],
                shard_norm=key[1],
            )
            prior = fresh.get(key)
            if prior is not None:
                row.brand_present = prior.brand_present
                row.winners = list(prior.winners or [])
                row.source = "reprobed"
                row.probe_status = "carried"
                row.probe_surface = prior.probe_surface
                row.probe_result_id = prior.probe_result_id
                row.probed_at = prior.probed_at
        row.issuing_surfaces = surfaces
        row.reach = len(surfaces)
        row.priority = shard_priority(row.brand_present, list(row.winners or []))
        session.add(row)
    session.flush()
    return len(observed)


@dataclass(frozen=True)
class ShardCandidate:
    """Plain snapshot of an unresolved shard for the re-probe ranking."""

    shard_id: int
    parent: str
    text: str
    reach: int
    parent_brand_absent: bool  # brand not named in any of the parent's answers
    shard_names_rival: bool  # the shard text itself names a competitor
    parent_names_rival: bool  # a competitor appears in the parent's answers
    names_brand: bool  # the shard itself names the brand (likely navigational)

    def score(self) -> tuple[int, int, int, int, int]:
        """Preliminary reach × loss (§2 option C): spend goes where a HIGH miss
        is likeliest to live. A rival named in the shard itself is a sharper
        signal than one named somewhere in the parent answer."""
        return (
            self.reach,
            int(self.parent_brand_absent),
            int(self.shard_names_rival),
            int(self.parent_names_rival),
            int(not self.names_brand),
        )


def select_candidates(
    candidates: list[ShardCandidate], per_prompt: int, per_run: int
) -> tuple[list[ShardCandidate], list[ShardCandidate], list[ShardCandidate]]:
    """Top-K per parent prompt, then the per-run ceiling across prompts.
    Returns (chosen, dropped_by_k, dropped_by_ceiling) — callers record the
    drops so no cap is silent (§8). Deterministic for a given input."""

    def order(c: ShardCandidate):
        return (tuple(-v for v in c.score()), c.parent, c.text.lower())

    by_parent: dict[str, list[ShardCandidate]] = defaultdict(list)
    for c in candidates:
        by_parent[c.parent].append(c)
    within_k: list[ShardCandidate] = []
    dropped_k: list[ShardCandidate] = []
    for parent in sorted(by_parent):
        ranked = sorted(by_parent[parent], key=order)
        within_k += ranked[: max(per_prompt, 0)]
        dropped_k += ranked[max(per_prompt, 0):]
    within_k.sort(key=order)
    chosen = within_k[: max(per_run, 0)]
    dropped_ceiling = within_k[max(per_run, 0):]
    return chosen, dropped_k, dropped_ceiling


def probe_surface_for(issuing: list[str], configured: set[str]) -> str | None:
    """The surface to re-probe a shard on: an engine that actually issued it
    (so presence is measured where the contest happened), cheapest first."""
    for surface in REPROBE_SURFACE_ORDER:
        if surface in issuing and surface in configured:
            return surface
    return None


def evaluate_probe(
    text: str,
    cited_domains: list[str],
    *,
    brand_name: str,
    brand_aliases: list[str],
    brand_domains: list[str],
    competitors: list[tuple[int | None, str, list[str], list[str]]],
) -> tuple[bool, list[str]]:
    """Presence + winners for one re-probe answer, from the same mention
    detector and owned-domain match the main pipeline uses. You're present if
    the answer names you or cites one of your domains; a competitor 'won' the
    shard on the same test. competitors = (id, name, aliases, domains)."""
    specs = [(cid, name, aliases) for cid, name, aliases, _domains in competitors]
    detected = detect_mentions(text, brand_name, brand_aliases, specs)
    brand_present = any(d.entity_type == "brand" for d in detected) or any(
        domain_is_owned(d, brand_domains) for d in cited_domains
    )
    named = {d.entity_name for d in detected if d.entity_type == "competitor"}
    winners = [
        name
        for _cid, name, _aliases, domains in competitors
        if name in named or any(domain_is_owned(d, domains) for d in cited_domains)
    ]
    return brand_present, winners
