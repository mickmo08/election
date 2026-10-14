"""'Synthetic Federation' (code XS): a fictional country used ONLY for demos and tests.

Using a fictional jurisdiction guarantees synthetic records can never be mistaken for, or
joined to, real election data. Every XS source is flagged is_synthetic and is refused in
production (see app.config.Settings.allows_synthetic_data).
"""

from __future__ import annotations

from datetime import date, timedelta

from .base import AdminUnitSpec, CalendarEntry, CountryAdapter, ElectoralSystemSpec, OfficeSpec, PartySpec, SourceSpec

REGIONS = [
    ("01", "Northmarch", "NM", 8), ("02", "Eastvale", "EV", 7), ("03", "Southreach", "SR", 6),
    ("04", "Westholm", "WH", 7), ("05", "Centralia", "CE", 9), ("06", "Islemoor", "IM", 3),
]


def synthetic_election_day(year: int) -> date:
    """Fictional rule: first Sunday of December in even years."""
    d = date(year, 12, 1)
    return d + timedelta(days=(6 - d.weekday()) % 7)


class SyntheticAdapter(CountryAdapter):
    code = "XS"
    name = "Synthetic Federation (fictional demo data)"
    default_timezone = "UTC"
    languages = ("en", "es")
    is_synthetic = True
    result_status_map = {"preliminary": "preliminary", "unofficial": "unofficial", "certified": "certified",
                         "corrected": "corrected", "recount": "recount"}

    def admin_levels(self) -> list[tuple[int, str]]:
        return [(0, "Federation"), (1, "Region")]

    def admin_units(self) -> list[AdminUnitSpec]:
        units = [AdminUnitSpec(0, "XS", "Synthetic Federation", "XS", None, "UTC")]
        units += [AdminUnitSpec(1, c, n, a, "XS", "UTC", {"assembly_seats": s}) for c, n, a, s in REGIONS]
        return units

    def electoral_systems(self) -> list[ElectoralSystemSpec]:
        return [
            ElectoralSystemSpec("fptp", "First past the post", "plurality"),
            ElectoralSystemSpec("list_pr_dhondt", "List PR (D'Hondt)", "proportional",
                                "Closed party lists, seats allocated by D'Hondt within each region."),
            ElectoralSystemSpec("two_round_majority", "Two-round majority", "majority"),
        ]

    def offices(self) -> list[OfficeSpec]:
        return [
            OfficeSpec("xs_assembly", "Assembly member", "Federal Assembly", 1, True, 40, "fptp"),
            OfficeSpec("xs_senate", "Senator (regional list)", "Federal Senate", 1, False, 24, "list_pr_dhondt"),
            OfficeSpec("xs_governor", "Regional governor", None, 1, False, None, "two_round_majority"),
        ]

    def parties(self) -> list[PartySpec]:
        return [
            PartySpec("xs_blue", "Harbor Alliance (fictional)", "HA", "#0f766e", ("HA", "HARBOR ALLIANCE")),
            PartySpec("xs_orange", "Meadow Party (fictional)", "MP", "#c2410c", ("MP", "MEADOW PARTY")),
            PartySpec("xs_purple", "Lantern Movement (fictional)", "LM", "#7c3aed", ("LM", "LANTERN MOVEMENT")),
        ]

    def calendar(self, year: int) -> list[CalendarEntry]:
        if year % 2:
            return []
        return [CalendarEntry("general", synthetic_election_day(year), "Fictional rule: first Sunday of December")]

    def publication_rules(self) -> dict:
        return {"poll_publication_blackout_days": 2}

    def sources(self) -> list[SourceSpec]:
        return [SourceSpec(
            key="xs-synthetic", name="Synthetic demo generator (fictional data)", publisher="Platform (synthetic)",
            owner_team="Platform", homepage_url="https://example.invalid/synthetic", access_method="synthetic_fixture",
            access_details="Deterministic generator app.ingestion.adapters.synthetic (seeded).",
            access_terms="Demo/test only.", license="Synthetic", license_url=None, permits_redistribution=True,
            permits_text_analysis=True, refresh_schedule="manual", freshness_sla_hours=None,
            coverage={"countries": ["XS"]}, reliability_notes="SYNTHETIC. Not real data. Never use for analysis.",
            data_kind="synthetic", adapter_key="synthetic_xs", required_credentials=(), default_status="active",
            status_reason="", remediation="", verification="n/a", is_synthetic=True,
        )]
