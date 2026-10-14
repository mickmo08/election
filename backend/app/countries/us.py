"""United States country adapter.

What is encoded here are *rules and stable reference standards* with citations:
  * state FIPS/USPS codes (ANSI INCITS 38), 2020-census House apportionment,
    Senate class membership (U.S. Const. art. I, sec. 3), in data/us_states.csv;
  * the federal general election date rule (2 U.S.C. 7; 2 U.S.C. 1).
Officeholders, candidates, primaries, special elections, district boundaries and
gubernatorial contests are NOT encoded: they are loaded from registered sources.
"""

from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path

from .base import (
    AdminUnitSpec,
    CalendarEntry,
    CountryAdapter,
    ElectoralSystemRule,
    ElectoralSystemSpec,
    OfficeSpec,
    PartySpec,
    SourceSpec,
)

DATA = Path(__file__).parent / "data"
UNVERIFIED = (
    "unverified_reference: transcribed from model knowledge (2026); must be confirmed against "
    "current state statute by the data owner before publication"
)


def federal_general_election_date(year: int) -> date:
    """Tuesday next after the first Monday in November (2 U.S.C. 7)."""
    if year % 2:
        raise ValueError("federal general elections are held in even-numbered years")
    d = date(year, 11, 1)
    first_monday = d + timedelta(days=(0 - d.weekday()) % 7)
    return first_monday + timedelta(days=1)


def load_states() -> list[dict]:
    with open(DATA / "us_states.csv", newline="") as fh:
        return list(csv.DictReader(fh))


class UnitedStatesAdapter(CountryAdapter):
    code = "US"
    name = "United States"
    default_timezone = "America/New_York"
    languages = ("en", "es")
    result_status_map = {
        "preliminary": "preliminary",
        "election night": "preliminary",
        "unofficial": "unofficial",
        "unofficial results": "unofficial",
        "semi-official": "unofficial",
        "official": "certified",
        "certified": "certified",
        "amended": "corrected",
        "corrected": "corrected",
        "recount": "recount",
        "recount results": "recount",
    }

    def admin_levels(self) -> list[tuple[int, str]]:
        return [(0, "Nation"), (1, "State, district or territory"), (2, "County or equivalent")]

    def admin_units(self) -> list[AdminUnitSpec]:
        units = [AdminUnitSpec(0, "US", "United States", "US", None, "America/New_York")]
        for row in load_states():
            units.append(
                AdminUnitSpec(
                    level=1,
                    code=row["fips"],
                    name=row["name"],
                    abbreviation=row["usps"],
                    parent_code="US",
                    timezone=row["timezone"],
                    attributes={
                        "house_seats_2020_apportionment": int(row["house_seats_2020"]),
                        "nonvoting_delegate": row["nonvoting_delegate"] == "true",
                        "senate_classes": [int(c) for c in row["senate_classes"].split("|") if c],
                    },
                )
            )
        return units

    def electoral_systems(self) -> list[ElectoralSystemSpec]:
        return [
            ElectoralSystemSpec("fptp", "First past the post", "plurality", "Single-member plurality."),
            ElectoralSystemSpec(
                "two_round_majority",
                "Majority with runoff",
                "majority",
                "A runoff is held if no candidate reaches the required threshold.",
            ),
            ElectoralSystemSpec(
                "rcv_irv", "Ranked-choice (instant runoff)", "ranked", "Single-winner instant-runoff voting."
            ),
            ElectoralSystemSpec(
                "top_two_primary",
                "Top-two nonpartisan primary",
                "majority",
                "All candidates on one primary ballot; top two advance.",
            ),
            ElectoralSystemSpec(
                "top_four_primary",
                "Top-four nonpartisan primary",
                "plurality",
                "All candidates on one primary ballot; top four advance.",
            ),
            ElectoralSystemSpec(
                "partisan_primary",
                "Partisan primary",
                "plurality",
                "Each party nominates separately; rules on runoffs vary by state.",
            ),
        ]

    def offices(self) -> list[OfficeSpec]:
        return [
            OfficeSpec("us_house", "U.S. Representative", "U.S. House of Representatives", 1, True, 435, "fptp"),
            OfficeSpec(
                "us_house_delegate",
                "Delegate / Resident Commissioner",
                "U.S. House of Representatives",
                1,
                False,
                None,
                "fptp",
            ),
            OfficeSpec("us_senate", "U.S. Senator", "U.S. Senate", 1, False, 100, "fptp"),
            OfficeSpec("governor", "Governor", None, 1, False, None, "fptp"),
            OfficeSpec("state_leg_upper", "State Senator", "State legislature (upper chamber)", 1, True, None, "fptp"),
            OfficeSpec(
                "state_leg_lower", "State Representative", "State legislature (lower chamber)", 1, True, None, "fptp"
            ),
            OfficeSpec("state_executive", "Other statewide executive office", None, 1, False, None, "fptp"),
        ]

    def electoral_system_rules(self) -> list[ElectoralSystemRule]:
        rules = []
        for office in ("us_house", "us_senate"):
            rules += [
                ElectoralSystemRule(
                    office, "23", "general", "rcv_irv", "Me. Rev. Stat. tit. 21-A, sec. 723-A", UNVERIFIED
                ),
                ElectoralSystemRule(office, "02", "primary", "top_four_primary", "Alaska Stat. 15.25.010", UNVERIFIED),
                ElectoralSystemRule(office, "02", "general", "rcv_irv", "Alaska Stat. 15.15.350", UNVERIFIED),
                ElectoralSystemRule(
                    office, "06", "primary", "top_two_primary", "Cal. Const. art. II, sec. 5", UNVERIFIED
                ),
                ElectoralSystemRule(office, "53", "primary", "top_two_primary", "RCW 29A.52.112", UNVERIFIED),
                ElectoralSystemRule(office, "13", "general", "two_round_majority", "O.C.G.A. 21-2-501", UNVERIFIED),
            ]
        return rules

    def parties(self) -> list[PartySpec]:
        # Label aliases seen in FEC and state returns. Colors follow common U.S. media convention.
        return [
            PartySpec(
                "dem",
                "Democratic Party",
                "DEM",
                "#2563eb",
                (
                    "DEM",
                    "DEMOCRAT",
                    "DEMOCRATIC",
                    "DEMOCRATIC PARTY",
                    "DEMOCRATIC-FARMER-LABOR",
                    "DFL",
                    "DEMOCRATIC-NPL",
                    "DEMOCRATIC-NONPARTISAN LEAGUE",
                ),
            ),
            PartySpec("rep", "Republican Party", "REP", "#dc2626", ("REP", "REPUBLICAN", "REPUBLICAN PARTY", "GOP")),
            PartySpec("lib", "Libertarian Party", "LIB", "#ca8a04", ("LIB", "LIBERTARIAN")),
            PartySpec("grn", "Green Party", "GRE", "#16a34a", ("GRE", "GREEN", "GREEN PARTY")),
            PartySpec(
                "ind",
                "Independent / no party",
                "IND",
                "#6b7280",
                (
                    "IND",
                    "INDEPENDENT",
                    "NPA",
                    "NO PARTY AFFILIATION",
                    "NONPARTISAN",
                    "UNAFFILIATED",
                    "NNE",
                    "NON-PARTY",
                ),
            ),
        ]

    def calendar(self, year: int) -> list[CalendarEntry]:
        if year % 2:
            return []
        d = federal_general_election_date(year)
        return [
            CalendarEntry(
                "general",
                d,
                "2 U.S.C. 7 (House); 2 U.S.C. 1 (Senate): Tuesday after the first "
                "Monday in November of even-numbered years",
            )
        ]

    def publication_rules(self) -> dict:
        return {
            "results_embargo": "Do not display results for a state until its last polls close "
            "(poll-closing times come from state sources).",
            "poll_publication_blackout_days": 0,
        }

    def sources(self) -> list[SourceSpec]:
        net = (
            "The build/test environment's egress policy blocks this host (HTTP 403 at proxy, verified "
            "2026-10-14). Allow-list the host in the deployment's egress policy."
        )
        return [
            SourceSpec(
                key="us-fec-openfec",
                name="OpenFEC API (candidates, committees, financial totals)",
                publisher="Federal Election Commission",
                owner_team="Data Engineering",
                homepage_url="https://api.open.fec.gov/developers/",
                access_method="api",
                access_details="GET https://api.open.fec.gov/v1/candidates/?election_year=YYYY&office=H|S"
                "&state=XX&per_page=100&page=N&api_key=KEY ; paginated JSON "
                "{pagination:{page,pages,count,per_page}, results:[...]}",
                access_terms="api.data.gov key required; rate limits apply per key (see api.data.gov).",
                license="U.S. Government work (public domain, 17 U.S.C. 105)",
                license_url=None,
                permits_redistribution=True,
                permits_text_analysis=False,
                refresh_schedule="0 6 * * *",
                freshness_sla_hours=48,
                coverage={"countries": ["US"], "offices": ["us_house", "us_senate"]},
                reliability_notes="Authoritative for federal candidate *filings*. A filing is not ballot "
                "qualification; ballot status comes from state election officials. No "
                "Senate seat class field, so concurrent special elections need editorial "
                "confirmation.",
                data_kind="candidates",
                adapter_key="us_fec_candidates",
                required_credentials=("ELECTION_FEC_API_KEY",),
                default_status="pending_credentials",
                status_reason="No FEC/api.data.gov key is provisioned. " + net,
                remediation="Request a key at https://api.data.gov/signup/, store it as ELECTION_FEC_API_KEY "
                "in the secret manager, allow api.open.fec.gov egress, then run ingestion.",
                verification="Endpoint pattern from FEC developer documentation (api.open.fec.gov/developers); "
                "not callable from the build environment.",
            ),
            SourceSpec(
                key="us-medsl-house",
                name="U.S. House 1976–2024 constituency returns",
                publisher="MIT Election Data and Science Lab (MEDSL)",
                owner_team="Data Engineering",
                homepage_url="https://electionlab.mit.edu/data",
                access_method="bulk_download",
                access_details="CSV from the MEDSL Harvard Dataverse record. Columns: year,state,state_po,"
                "state_fips,state_cen,state_ic,office,district,stage,runoff,special,candidate,"
                "party,writein,mode,candidatevotes,totalvotes,unofficial,version,fusion_ticket",
                access_terms="Dataverse terms of use; cite the dataset DOI.",
                license="Per Dataverse record (verify; MEDSL datasets are commonly CC0)",
                license_url=None,
                permits_redistribution=False,
                permits_text_analysis=False,
                refresh_schedule="after each release",
                freshness_sla_hours=None,
                coverage={"countries": ["US"], "offices": ["us_house"], "years": "1976-2024"},
                reliability_notes="Research-grade compilation of official returns; check the `version` and "
                "`unofficial` columns. Not a live results source.",
                data_kind="historical_results",
                adapter_key="medsl_returns",
                required_credentials=(),
                default_status="network_blocked",
                status_reason=net,
                remediation="Download the CSV from the Dataverse record (confirm DOI and licence), then upload "
                "via Sources > Upload or allow dataverse.harvard.edu egress.",
                verification="Column layout per MEDSL codebook; DOI to be recorded by data owner.",
            ),
            SourceSpec(
                key="us-medsl-senate",
                name="U.S. Senate 1976–2024 statewide returns",
                publisher="MIT Election Data and Science Lab (MEDSL)",
                owner_team="Data Engineering",
                homepage_url="https://electionlab.mit.edu/data",
                access_method="bulk_download",
                access_details="CSV from the MEDSL Harvard Dataverse record (same layout as House, district "
                "= 'statewide').",
                access_terms="Dataverse terms of use; cite the dataset DOI.",
                license="Per Dataverse record (verify)",
                license_url=None,
                permits_redistribution=False,
                permits_text_analysis=False,
                refresh_schedule="after each release",
                freshness_sla_hours=None,
                coverage={"countries": ["US"], "offices": ["us_senate"], "years": "1976-2024"},
                reliability_notes="As for the House file.",
                data_kind="historical_results",
                adapter_key="medsl_returns",
                required_credentials=(),
                default_status="network_blocked",
                status_reason=net,
                remediation="As for us-medsl-house.",
                verification="Column layout per MEDSL codebook.",
            ),
            SourceSpec(
                key="us-census-cd-boundaries",
                name="Congressional district boundaries (cartographic boundary files)",
                publisher="U.S. Census Bureau",
                owner_team="Geo Data",
                homepage_url="https://www.census.gov/geographies/mapping-files/time-series/geo/cartographic-boundary.html",
                access_method="bulk_download",
                access_details="Zipped shapefile, e.g. cb_<year>_us_cd<congress>_500k.zip; fields STATEFP, "
                "CD<congress>FP, GEOID, NAMELSAD. Loaded with the census_cd_shapefile adapter.",
                access_terms="Public domain.",
                license="U.S. Government work (public domain)",
                license_url=None,
                permits_redistribution=True,
                permits_text_analysis=False,
                refresh_schedule="annual",
                freshness_sla_hours=None,
                coverage={"countries": ["US"], "offices": ["us_house"]},
                reliability_notes="Census files lag mid-decade redistricting. Several states adopted new maps "
                "for 2026; those plans must come from state redistricting authorities.",
                data_kind="boundaries",
                adapter_key="census_cd_shapefile",
                required_credentials=(),
                default_status="network_blocked",
                status_reason=net,
                remediation="Allow www2.census.gov egress or upload the zip; add state redistricting sources "
                "for plans enacted after the Census vintage.",
                verification="File naming per Census cartographic boundary documentation.",
            ),
            SourceSpec(
                key="us-state-official-results",
                name="State election authority official results",
                publisher="State and territorial election officials",
                owner_team="Results Desk",
                homepage_url="https://www.eac.gov/",
                access_method="bulk_download",
                access_details="Per-state formats differ. Each state needs a mapping into the normalized "
                "official_results_csv format (docs/adapters/official-results-format.md).",
                access_terms="Varies by state; record per-state terms before enabling.",
                license="Varies by state",
                license_url=None,
                permits_redistribution=False,
                permits_text_analysis=False,
                refresh_schedule="election night: every 5 min; otherwise daily",
                freshness_sla_hours=24,
                coverage={"countries": ["US"]},
                reliability_notes="Authoritative. Reporting completeness is shown only when the state feed "
                "provides it.",
                data_kind="official_results",
                adapter_key="official_results_csv",
                required_credentials=(),
                default_status="unavailable",
                status_reason="No state-specific feed mappings are configured yet.",
                remediation="Configure a mapping per state (owner: Results Desk) and verify against a past "
                "certified canvass before election night.",
                verification="Not yet verified per state.",
            ),
            SourceSpec(
                key="us-licensed-results-feed",
                name="Licensed election-night results and race-call feed",
                publisher="Commercial election data provider (to be contracted)",
                owner_team="Results Desk",
                homepage_url="https://example.invalid/contract-required",
                access_method="licensed_feed",
                access_details="To be defined by the contracted provider's API documentation.",
                access_terms="Commercial licence required.",
                license="Commercial (not yet licensed)",
                license_url=None,
                permits_redistribution=False,
                permits_text_analysis=False,
                refresh_schedule="streaming on election night",
                freshness_sla_hours=1,
                coverage={"countries": ["US"]},
                reliability_notes="Not contracted.",
                data_kind="official_results",
                adapter_key=None,
                required_credentials=(),
                default_status="pending_license",
                status_reason="No licence agreement in place.",
                remediation="Business decision + contract; then implement the provider adapter.",
                verification="n/a",
            ),
            SourceSpec(
                key="editorial-desk",
                name="Editorial desk (race calls and curated contest calendar)",
                publisher="Platform editorial team",
                owner_team="Editorial",
                homepage_url="https://example.invalid/editorial-policy",
                access_method="editorial",
                access_details="Entered by authorised editors in the admin UI/API; every contest calendar "
                "row requires a citation URL to an official source.",
                access_terms="Internal.",
                license="Internal",
                license_url=None,
                permits_redistribution=True,
                permits_text_analysis=False,
                refresh_schedule="as needed",
                freshness_sla_hours=None,
                coverage={"countries": ["*"]},
                reliability_notes="Race calls follow docs/policies/editorial-race-call-policy.md.",
                data_kind="editorial",
                adapter_key="editorial_contests_csv",
                required_credentials=(),
                default_status="active",
                status_reason="",
                remediation="",
                verification="Internal source.",
            ),
            SourceSpec(
                key="us-polls-editorial",
                name="Published polls entered from pollster releases",
                publisher="Pollsters (as published)",
                owner_team="Polling Desk",
                homepage_url="https://example.invalid/polling-standards",
                access_method="manual_upload",
                access_details="polls_csv format with full methodology fields; release URL required.",
                access_terms="Only toplines and methodology published by the pollster are stored.",
                license="Facts as published; cite pollster release",
                license_url=None,
                permits_redistribution=False,
                permits_text_analysis=False,
                refresh_schedule="as published",
                freshness_sla_hours=168,
                coverage={"countries": ["US"]},
                reliability_notes="Quality depends on pollster disclosure; nonprobability samples get no "
                "margin of error.",
                data_kind="polls",
                adapter_key="polls_csv",
                required_credentials=(),
                default_status="active",
                status_reason="",
                remediation="",
                verification="Internal workflow.",
            ),
            SourceSpec(
                key="us-licensed-news",
                name="Licensed news archive for issue analysis",
                publisher="News licensing provider (to be contracted)",
                owner_team="Issues Desk",
                homepage_url="https://example.invalid/contract-required",
                access_method="licensed_feed",
                access_details="documents_jsonl export from the licensed provider.",
                access_terms="Text analysis must be expressly permitted by the licence.",
                license="Commercial (not yet licensed)",
                license_url=None,
                permits_redistribution=False,
                permits_text_analysis=False,
                refresh_schedule="hourly",
                freshness_sla_hours=6,
                coverage={"countries": ["US"]},
                reliability_notes="Not contracted.",
                data_kind="news",
                adapter_key="documents_jsonl",
                required_credentials=(),
                default_status="pending_license",
                status_reason="No licence permitting text analysis is in place.",
                remediation="Contract a provider whose licence permits text and data mining; record terms.",
                verification="n/a",
            ),
        ]
