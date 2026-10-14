"""Contract tests every country adapter must pass (docs/adapters/country-adapter-contract.md)."""

from datetime import date

import pytest

from app.countries.registry import ADAPTERS
from app.countries.us import UnitedStatesAdapter, federal_general_election_date, load_states
from app.models.provenance import ACCESS_METHODS, SOURCE_STATUSES

CANONICAL = {"preliminary", "unofficial", "certified", "corrected", "recount"}


@pytest.mark.parametrize("adapter", list(ADAPTERS.values()), ids=lambda a: a.code)
class TestContract:
    def test_admin_hierarchy(self, adapter):
        levels = [lvl for lvl, _ in adapter.admin_levels()]
        assert levels == list(range(len(levels))), "levels must be contiguous from 0"
        units = adapter.admin_units()
        codes = {u.code for u in units}
        assert len(codes) == len(units), "unit codes unique"
        roots = [u for u in units if u.parent_code is None]
        assert len(roots) == 1 and roots[0].level == 0
        for u in units:
            assert u.level in levels
            if u.parent_code:
                parent = next(p for p in units if p.code == u.parent_code)
                assert parent.level == u.level - 1

    def test_offices_reference_known_systems(self, adapter):
        systems = {s.key for s in adapter.electoral_systems()}
        for o in adapter.offices():
            assert o.default_electoral_system in systems
            assert o.jurisdiction_level in [lvl for lvl, _ in adapter.admin_levels()]
        for r in adapter.electoral_system_rules():
            assert r.system_key in systems and r.citation and r.verification

    def test_calendar_rules_are_cited(self, adapter):
        for year in (2022, 2024, 2026):
            for e in adapter.calendar(year):
                assert e.basis and e.election_date.year == year

    def test_sources_are_documented(self, adapter):
        for s in adapter.sources():
            assert s.access_method in ACCESS_METHODS
            assert s.default_status in SOURCE_STATUSES
            assert s.license and s.owner_team and s.reliability_notes
            if s.default_status != "active":
                assert s.status_reason and s.remediation, f"{s.key} unavailable without remediation"
            assert s.is_synthetic == adapter.is_synthetic

    def test_status_vocabulary_is_canonical(self, adapter):
        assert set(adapter.result_status_map.values()) <= CANONICAL
        with pytest.raises(ValueError):
            adapter.normalize_status("definitely-not-a-status")

    def test_parties_have_unique_keys(self, adapter):
        keys = [p.key for p in adapter.parties()]
        assert len(keys) == len(set(keys))


def test_us_reference_consistency():
    states = load_states()
    assert sum(int(s["house_seats_2020"]) for s in states) == 435
    voting = [s for s in states if s["nonvoting_delegate"] == "false"]
    assert len(voting) == 50
    for s in voting:
        assert len(s["senate_classes"].split("|")) == 2
    counts = {c: sum(c in s["senate_classes"].split("|") for s in voting) for c in "123"}
    assert counts == {"1": 33, "2": 33, "3": 34}


def test_federal_election_date_rule():
    assert federal_general_election_date(2026) == date(2026, 11, 3)
    assert federal_general_election_date(2024) == date(2024, 11, 5)
    assert federal_general_election_date(2020) == date(2020, 11, 3)
    assert federal_general_election_date(2018) == date(2018, 11, 6)
    with pytest.raises(ValueError):
        federal_general_election_date(2025)


def test_us_system_overrides():
    us = UnitedStatesAdapter()
    assert us.system_for("us_house", "23", "general") == "rcv_irv"  # Maine
    assert us.system_for("us_house", "06", "primary") == "top_two_primary"  # California
    assert us.system_for("us_house", "48", "general") == "fptp"
