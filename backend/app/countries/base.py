"""Country adapter contract.

A country adapter declares everything the core platform needs to model one country's
elections without schema changes: administrative hierarchy, offices, electoral systems,
calendar rules, publication rules, status vocabularies and registered sources.

The contract is exercised by tests/test_country_contract.py against every registered
adapter. See docs/adapters/country-adapter-contract.md for the full specification.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class ElectoralSystemSpec:
    key: str
    name: str
    family: str  # plurality | majority | proportional | mixed | ranked
    description: str = ""


@dataclass(frozen=True)
class OfficeSpec:
    key: str
    name: str
    body: str | None
    jurisdiction_level: int
    districted: bool
    total_seats: int | None
    default_electoral_system: str


@dataclass(frozen=True)
class AdminUnitSpec:
    level: int
    code: str
    name: str
    abbreviation: str | None = None
    parent_code: str | None = None
    timezone: str | None = None
    attributes: dict = field(default_factory=dict)


@dataclass(frozen=True)
class PartySpec:
    key: str
    name: str
    abbreviation: str | None
    color: str | None
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class CalendarEntry:
    """An election date derived from a rule (statute/constitution), never a guess."""

    kind: str
    election_date: date
    basis: str  # citation of the rule
    admin_unit_code: str | None = None


@dataclass(frozen=True)
class ElectoralSystemRule:
    """A (office, admin unit) specific system override with its legal citation."""

    office_key: str
    admin_unit_code: str
    stage: str  # primary | general | runoff
    system_key: str
    citation: str
    verification: str  # e.g. "unverified_reference: confirm against current statute"


@dataclass(frozen=True)
class SourceSpec:
    key: str
    name: str
    publisher: str
    owner_team: str
    homepage_url: str
    access_method: str
    access_details: str
    access_terms: str
    license: str
    license_url: str | None
    permits_redistribution: bool
    permits_text_analysis: bool
    refresh_schedule: str
    freshness_sla_hours: int | None
    coverage: dict
    reliability_notes: str
    data_kind: str
    adapter_key: str | None
    required_credentials: tuple[str, ...]
    default_status: str
    status_reason: str
    remediation: str
    verification: str
    is_synthetic: bool = False


class CountryAdapter(ABC):
    code: str
    name: str
    default_timezone: str
    languages: tuple[str, ...]
    is_synthetic: bool = False
    # Canonical result statuses: preliminary, unofficial, certified, corrected, recount.
    result_status_map: dict[str, str] = {}

    @abstractmethod
    def admin_levels(self) -> list[tuple[int, str]]: ...

    @abstractmethod
    def admin_units(self) -> list[AdminUnitSpec]: ...

    @abstractmethod
    def electoral_systems(self) -> list[ElectoralSystemSpec]: ...

    @abstractmethod
    def offices(self) -> list[OfficeSpec]: ...

    @abstractmethod
    def calendar(self, year: int) -> list[CalendarEntry]:
        """Only dates fixed by rule. Dates set administratively come from sources."""

    @abstractmethod
    def sources(self) -> list[SourceSpec]: ...

    def electoral_system_rules(self) -> list[ElectoralSystemRule]:
        return []

    def parties(self) -> list[PartySpec]:
        """Canonical parties with label aliases used for identity resolution. Others are created
        on first sight and flagged for review."""
        return []

    def publication_rules(self) -> dict:
        """E.g. poll publication blackout days, results embargo until polls close."""
        return {}

    def normalize_status(self, label: str) -> str:
        key = label.strip().lower()
        if key in self.result_status_map:
            return self.result_status_map[key]
        raise ValueError(f"unknown result status label {label!r} for {self.code}")

    def system_for(self, office_key: str, admin_unit_code: str | None, stage: str) -> str:
        for rule in self.electoral_system_rules():
            if rule.office_key == office_key and rule.admin_unit_code == admin_unit_code and rule.stage == stage:
                return rule.system_key
        for office in self.offices():
            if office.key == office_key:
                return office.default_electoral_system
        raise KeyError(office_key)
