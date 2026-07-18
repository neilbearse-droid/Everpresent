"""Selective query×persona matrix (GoDaddy step 3). The presence of a 'generic'
persona flips a tenant into curated-matrix mode; tenants without one keep the
pre-matrix full cross-product (Mode A) / first-persona-only (Mode B)."""

from worker.jobs import matrix_cells

# (id, name, prompt, segment)
GENERIC = (1, "Generic", "", "generic")
DREAMER = (2, "Dreamer", "I want a domain.", "dreamer")
INVESTOR = (3, "Investor", "I flip domains.", "domain_investor")


def _q(qid, text, runs=None):
    return (qid, text, runs or [])


def test_selective_mode_runs_generic_plus_named_personas():
    queries = [
        _q(1, "buy a domain", [{"segment": "dreamer"}, {"segment": "domain_investor"}]),
        _q(2, "privacy accuracy", []),  # generic only — clean specimen
    ]
    personas = [GENERIC, DREAMER, INVESTOR]
    cells = matrix_cells(queries, personas)
    # Q1: generic + dreamer + investor = 3; Q2: generic only = 1.
    q1 = [c for c in cells if c[0] == 1]
    q2 = [c for c in cells if c[0] == 2]
    assert {c[2][3] for c in q1} == {"generic", "dreamer", "domain_investor"}
    assert [c[2][3] for c in q2] == ["generic"]


def test_vertical_overlay_appends_clause_and_labels_run():
    queries = [_q(1, "build an app", [{"segment": "dreamer", "overlay": "It's a restaurant."}])]
    cells = matrix_cells(queries, [GENERIC, DREAMER])
    overlay = next(c for c in cells if c[2][3] == "dreamer")
    _pid, name, prompt, seg = overlay[2]
    assert prompt == "I want a domain. It's a restaurant."
    assert name == "Dreamer (It's a restaurant.)"
    assert seg == "dreamer"  # still rolls up under the base segment


def test_unknown_segment_is_skipped_not_crashed():
    queries = [_q(1, "q", [{"segment": "no_such_segment"}])]
    cells = matrix_cells(queries, [GENERIC, DREAMER])
    assert [c[2][3] for c in cells] == ["generic"]  # only the baseline


def test_legacy_mode_a_is_full_cross_product():
    # No 'generic' persona → unchanged pre-matrix behaviour.
    queries = [_q(1, "a"), _q(2, "b")]
    personas = [DREAMER, INVESTOR]
    cells = matrix_cells(queries, personas)
    assert len(cells) == 4  # 2 queries × 2 personas
    assert {c[2][3] for c in cells} == {"dreamer", "domain_investor"}


def test_legacy_mode_b_is_first_persona_only():
    queries = [_q(1, "a"), _q(2, "b")]
    personas = [DREAMER, INVESTOR]
    cells = matrix_cells(queries, personas, first_persona_only=True)
    assert len(cells) == 2  # first persona only, one per query
    assert {c[2][3] for c in cells} == {"dreamer"}


def test_godaddy_seed_matrix_matches_brief():
    from pathlib import Path

    from api.yaml_import import parse_config_yaml

    spec = parse_config_yaml((Path(__file__).parent.parent / "seeds" / "godaddy.yaml").read_text())
    queries = [(i, q.text, q.persona_runs()) for i, q in enumerate(spec.queries)]
    personas = [(i, p.name, p.prompt, p.segment) for i, p in enumerate(spec.personas)]
    cells = matrix_cells(queries, personas)
    generic = [c for c in cells if c[2][3] == "generic"]
    persona = [c for c in cells if c[2][3] != "generic"]
    # The brief: all 10 queries generic + 15 persona-query combinations.
    assert len(generic) == 10
    assert len(persona) == 15
