"""The weekly briefing: three answers on one screen.

  Are we winning?  the headline mention rate, its range and real change,
                   and how we compare with the top rival
  Why?             the strongest reasons in the data right now: a real
                   change on one engine, a model switch, memory vs search,
                   the top objection, a wrong fact
  This week        the top open plays from the playbook

Pure composition of existing reads; nothing new is measured here."""

from typing import Any

from sqlmodel import Session, col, select

from api.models import Recommendation, RecommendationStatus


def briefing(session: Session, tenant_id: int) -> dict[str, Any]:
    from api.answer_shape_service import answer_shape
    from api.dashboards_service import _brand_name, alerts, mention_rates, overview

    brand = _brand_name(session, tenant_id)
    rates = mention_rates(session, tenant_id)
    o = rates["overall"]
    sov = (overview(session, tenant_id) or {}).get("share_of_voice") or {}
    rivals = sorted(((n, v) for n, v in sov.items() if n != brand), key=lambda kv: -kv[1])
    top_rival = {"name": rivals[0][0], "share": rivals[0][1]} if rivals else None

    if not o.get("answers"):
        verdict, line = "unknown", "No measured answers yet. The first run fills this in."
    else:
        ch = o["change"]["verdict"]
        delta = o["change"].get("delta")
        if ch == "up":
            verdict = "gaining"
            line = f"You're named in {o['rate']}% of answers, up {delta} points."
        elif ch == "down":
            verdict, line = "losing", (f"You're named in {o['rate']}% of answers, down "
                                       f"{abs(delta or 0)} points.")
        else:
            verdict = "holding" if ch == "no real change" else "baseline"
            line = (f"You're named in {o['rate']}% of answers ({o['low']}–{o['high']}%), "
                    + ("with no real change in the last four weeks." if ch == "no real change"
                       else "too few answers yet to call a change."))
        if top_rival and sov.get(brand) is not None:
            mine = sov.get(brand, 0)
            name, theirs = top_rival["name"], top_rival["share"]
            if theirs > mine:
                line += f" {name} leads share of voice ({theirs}% vs your {mine}%)."
            else:
                line += f" You lead share of voice ({mine}% vs {name} {theirs}%)."

    reasons: list[dict[str, str]] = []
    top_alerts = alerts(session, tenant_id)[:3]
    for a in top_alerts:
        reasons.append({"kind": a.get("kind", ""), "tone": a.get("severity", "medium"),
                        "text": a.get("text", "")})
    shape = answer_shape(session, tenant_id)
    if shape.get("has_data"):
        for ch in shape["model_changes"][:1]:
            reasons.append({"kind": "model", "tone": "medium",
                            "text": f"{ch['label']} switched to {ch['model']} on {ch['since']}: "
                                    "compare before and after with care."})
        gaps = [m for m in shape["memory_vs_search"]
                if m["verdict"] == "known, but losing in search"]
        if gaps:
            reasons.append({"kind": "memory", "tone": "medium",
                            "text": f"{gaps[0]['label']} knows you from memory but names you less "
                                    "when it searches: fix what search retrieves."})
        themes = [t for t in shape["perception"]["themes"] if t["objections"]]
        if themes:
            t = themes[0]
            example = f" e.g. “{t['examples'][0][:140]}”" if t["examples"] else ""
            reasons.append({"kind": "objection",
                            "tone": "high" if t["objections"] >= 5 else "medium",
                            "text": f"The objection engines raise most about you: "
                                    f"{t['theme'].lower()} ({t['objections']} times).{example}"})
    from api.agent_picks_service import agent_picks

    picks = agent_picks(session, tenant_id)
    if picks["has_data"] and picks["overall"]["top_rival"]:
        mine, rival = picks["overall"]["first_pick"], picks["overall"]["top_rival"]
        if rival["rate"] > mine["high"]:
            # Ahead of the softer reasons, so the four-reason cap keeps it.
            reasons.insert(len(top_alerts), {"kind": "agent_pick", "tone": "high",
                            "text": f"When asked to do the job, AI picks {rival['name']} first "
                                    f"in {rival['rate']}% of answers; you {mine['rate']}%."})
    plays = session.exec(
        select(Recommendation).where(
            Recommendation.tenant_id == tenant_id,
            col(Recommendation.status).in_([RecommendationStatus.open,
                                            RecommendationStatus.in_progress]),
            Recommendation.branch != "strategy",
        ).order_by(col(Recommendation.priority).desc(), col(Recommendation.gap_ref)).limit(3)
    ).all()
    focus = session.exec(
        select(Recommendation).where(Recommendation.tenant_id == tenant_id,
                                     Recommendation.branch == "strategy")
    ).first()
    return {
        "brand": brand,
        "winning": {"verdict": verdict, "line": line, "rate": o.get("rate"),
                    "low": o.get("low"), "high": o.get("high"), "answers": o.get("answers", 0),
                    "change": o.get("change"), "top_rival": top_rival},
        "why": reasons[:4],
        "this_week": [{"id": p.id, "title": p.title or p.action_text[:80], "kind": p.branch,
                       "evidence": p.evidence, "why": p.why, "link": p.link,
                        "status": str(p.status)}
                      for p in plays],
        "focus": focus.title.removeprefix("Focus:").strip() if focus else None,
    }
