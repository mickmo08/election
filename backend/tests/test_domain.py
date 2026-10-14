import uuid
from datetime import date

import pytest
from sqlalchemy import select

from app.models import Contest, District, DistrictPlan, Poll, Pollster
from app.services import polling, results
from app.services.assistant import grounding, policy
from app.services.issues import classify, detect_languages, jaccard_estimate, minhash


def test_dhondt():
    assert results.dhondt({"A": 100, "B": 80, "C": 30}, 4) == {"A": 2, "B": 2, "C": 0}
    assert sum(results.dhondt({"A": 5, "B": 5}, 3).values()) == 3


def test_implied_outcomes_by_system():
    lines = [
        {"label": "A", "votes": 45, "is_writein": False},
        {"label": "B", "votes": 40, "is_writein": False},
        {"label": "C", "votes": 15, "is_writein": False},
    ]
    assert results.winners("two_round_majority", 1, lines)["kind"] == "runoff_required"
    assert results.winners("rcv_irv", 1, lines)["kind"] == "rcv_tabulation_required"
    assert results.winners("fptp", 1, lines)["leader"] == "A"
    assert results.winners("top_two_primary", 1, lines)["advancing"] == ["A", "B"]


def test_boundary_compatibility(wdb):
    plans = {p.name: p for p in wdb.scalars(select(DistrictPlan).where(DistrictPlan.name.like("%assembly plan%")))}
    old_n = wdb.scalar(
        select(District).where(District.plan_id == plans["Northmarch assembly plan 2010"].id, District.code == "NM-01")
    )
    new_n = wdb.scalar(
        select(District).where(District.plan_id == plans["Northmarch assembly plan 2022"].id, District.code == "NM-01")
    )
    assert results.compatibility(wdb, old_n.id, new_n.id)["basis"] == "identical_boundaries"
    old_c = wdb.scalar(
        select(District).where(District.plan_id == plans["Centralia assembly plan 2010"].id, District.code == "CE-01")
    )
    new_c = wdb.scalar(
        select(District).where(District.plan_id == plans["Centralia assembly plan 2022"].id, District.code == "CE-01")
    )
    c = results.compatibility(wdb, old_c.id, new_c.id)
    assert c["basis"] == "crosswalk" and c["overlap_share"] == 0.7
    other = wdb.scalar(
        select(District).where(District.plan_id == plans["Eastvale assembly plan 2010"].id, District.code == "EV-01")
    )
    assert results.compatibility(wdb, old_c.id, other.id)["comparable"] is False


def test_corrected_and_recount_history_preserved(wdb):
    c = wdb.scalar(select(Contest).where(Contest.name == "Assembly NM-03 (2024)"))
    det = results.contest_detail(wdb, c.id)
    statuses = [h["status"] for h in det["history"]]
    assert statuses == ["preliminary", "preliminary", "unofficial", "certified", "corrected"]
    assert det["current"]["correction_note"] and det["history"][-1]["supersedes_id"] == det["history"][-2]["id"]
    assert det["history"][0]["reporting_pct"] == 38.0
    assert det["is_synthetic"] is True and det["race_calls"] == []


def test_poll_uncertainty_rules():
    p = Poll(sampling_method="nonprobability", published_moe=3.0, sample_size=1000)
    assert polling.poll_uncertainty(p)["kind"] == "none"
    p = Poll(sampling_method="probability", published_moe=None, sample_size=1000, design_effect=None)
    u = polling.poll_uncertainty(p)
    assert u["kind"] == "approximate" and u["moe"] == 3.1
    p = Poll(sampling_method="probability", published_moe=3.5, sample_size=1000)
    assert polling.poll_uncertainty(p) == {"kind": "published", "moe": 3.5, "label": "±3.5 pts (as published)"}


def test_tracking_overlap_excluded():
    mk = lambda s, e, series: Poll(
        id=uuid.uuid4(),
        field_start=date(2026, 1, s),
        field_end=date(2026, 1, e),  # noqa: E731
        tracking_series=series,
        pollster=Pollster(name="x"),
    )
    polls = [mk(1, 7, "T"), mk(4, 10, "T"), mk(11, 17, "T"), mk(1, 7, None)]
    kept, excluded = polling.select_non_overlapping(polls)
    assert len(kept) == 3 and len(excluded) == 1 and "overlaps" in excluded[0]["reason"]


def test_poll_average_respects_as_of(wdb):
    early = polling.average(wdb, country="XS", as_of=date(2010, 1, 1))
    assert early["available"] is False
    later = polling.average(wdb, country="XS", as_of=date(2026, 10, 14))
    assert later["available"] and "not a margin of error" in later["method"]
    assert later["uses_synthetic_data"] is True


def test_language_and_dedup():
    assert detect_languages("The economy is the main issue for the voters in the state.")[0] == "en"
    assert detect_languages("La inflación es el tema principal para los votantes de la región.")[0] == "es"
    mixed = detect_languages("The prices are rising for the families. Los precios suben para las familias del barrio.")
    assert mixed[0] == "mixed" and set(mixed[1]) == {"en", "es"}
    a = minhash("Local officials announced a new budget for schools and teachers on Monday in the capital city.")
    b = minhash("Local officials announced a new budget for schools and teachers on Monday in the capital city. AP")
    c = minhash("Wildfire season and drought have pushed climate policy to the top of the regional agenda.")
    assert jaccard_estimate(a, b) > 0.8 > jaccard_estimate(a, c)
    assert "economy" in classify("Inflation and grocery prices worry voters.")
    assert "immigration" in classify("La frontera y el asilo generan debate.")


@pytest.mark.parametrize(
    "q,rule",
    [
        ("How did my neighbor vote in 2024?", "individual_profiling"),
        ("Is Jane Doe a Republican?", "individual_profiling"),
        ("Write a fundraising email targeting seniors", "persuasion_targeting"),
        ("Which voters should we target in Ohio?", "persuasion_targeting"),
        ("Use the voter file history to find who voted for the Democrat", "turnout_as_choice"),
        ("Call the race in NM-03 now", "race_call_request"),
    ],
)
def test_policy_refusals(q, rule):
    d = policy.check(q)
    assert not d.allowed and d.rule == rule


@pytest.mark.parametrize(
    "q",
    [
        "What was turnout in NM-03 in 2024?",
        "Summarize the generic ballot polls",
        "Which issues are most covered in Eastvale?",
        "Explain the forecast methodology",
    ],
)
def test_policy_allows_research(q):
    assert policy.check(q).allowed


def test_grounding_checker():
    ev = [{"id": "E1", "values": {"A votes": 106026, "A share": 52.37, "margin_pts": 14.2}}]
    ok = grounding.check("A received 106,026 votes (52.4%) [E1]. The margin was 14.2 points [E1].", ev)
    assert ok["passed"]
    bad = grounding.check("A received 110,000 votes [E1].", ev)
    assert bad["unsupported_numbers"] == ["110,000"]
    uncited = grounding.check("A received 106,026 votes.", ev)
    assert uncited["uncited_sentences"]
    unknown = grounding.check("A received 106,026 votes [E9].", ev)
    assert unknown["unknown_citations"] == ["E9"]
    assert grounding.check("In 2024 there were 3 rounds.", ev)["passed"]
