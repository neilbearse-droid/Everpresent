"""Compatibility shim: the dashboard reads now live in api/dashboards/, one
module per page. Every name, private helpers included, is re-exported here
so existing imports keep working."""

from api.dashboards.action_plan import (  # noqa: F401
    _DEPENDENCE_WEIGHT,
    _LISTICLE_RE,
    _MAX_DIFF_WINNERS,
    CONTEST_WINDOW_DAYS,
    _brief_outline,
    _citability_diff,
    _contestability,
    _lost_citations,
    _page_url,
    _spam_risk,
    action_plan,
)
from api.dashboards.brand import (  # noqa: F401
    accuracy_report,
    brand_report,
    whitespace_report,
)
from api.dashboards.citations import (  # noqa: F401
    MAX_CONSULTED_DOMAINS,
    MAX_POWER_PAGES,
    citations_intel,
)
from api.dashboards.common import (  # noqa: F401
    _as_utc,
    _brand_and_cited_ids,
    _brand_name,
    _branded_query_texts,
    _clean_date,
    _date_in_range,
    _date_window,
    _in_window,
    _latest_results_by_variant,
    _mean,
    _owned_domains,
    _pct,
    _stdev,
    _surface_label,
    _utc,
)
from api.dashboards.engines import (  # noqa: F401
    _BROWSER_SURFACES,
    _DIAGNOSIS,
    _FORCED_SEARCH_SURFACES,
    _MODE_PLAY,
    _RECALL_AT,
    _RETRIEVE_AT,
    _SERP_SURFACES,
    engine_modes,
    engine_scorecard,
    routing_report,
)
from api.dashboards.fanout import (  # noqa: F401
    _fanout_by_query,
    fanout_report,
    fanout_scorecard,
)
from api.dashboards.measurement import (  # noqa: F401
    MENTION_WINDOW_DAYS,
    STABILITY_RUNS,
    alerts,
    kpi_scorecard,
    mention_rates,
)
from api.dashboards.outcome import (  # noqa: F401
    interventions_report,
    outcome,
)
from api.dashboards.overview import (  # noqa: F401
    MAX_MOVERS,
    SERIES_BREAKS,
    SOV_DAYS,
    TREND_DAYS,
    _series_notes,
    aio_summary,
    overview,
    personas,
)
from api.dashboards.queries import (  # noqa: F401
    queries_intel,
)
