"""Global electoral geography and election structure.

Nothing here is U.S.-specific: countries define their own administrative hierarchy,
offices, electoral systems, party systems and calendars via country adapters.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, created_at, uuid_pk


class Country(Base):
    __tablename__ = "countries"
    code: Mapped[str] = mapped_column(String(8), primary_key=True)  # ISO 3166-1 alpha-2, or X* for synthetic
    name: Mapped[str] = mapped_column(String(200))
    adapter_key: Mapped[str] = mapped_column(String(64))
    default_timezone: Mapped[str] = mapped_column(String(64))
    languages: Mapped[list] = mapped_column(JSONB, default=list)
    publication_rules: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)


class AdminLevel(Base):
    __tablename__ = "admin_levels"
    __table_args__ = (UniqueConstraint("country_code", "level"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    country_code: Mapped[str] = mapped_column(ForeignKey("countries.code"))
    level: Mapped[int] = mapped_column(Integer)  # 0 = country, 1 = first-order subdivision...
    name: Mapped[str] = mapped_column(String(100))


class AdminUnit(Base):
    __tablename__ = "admin_units"
    __table_args__ = (UniqueConstraint("country_code", "level", "code", "valid_from"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    country_code: Mapped[str] = mapped_column(ForeignKey("countries.code"), index=True)
    level: Mapped[int] = mapped_column(Integer)
    code: Mapped[str] = mapped_column(String(32))
    abbreviation: Mapped[str | None] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(200))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("admin_units.id"))
    timezone: Mapped[str | None] = mapped_column(String(64))
    valid_from: Mapped[date] = mapped_column(Date, default=date(1900, 1, 1))
    valid_to: Mapped[date | None] = mapped_column(Date)
    source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sources.id"))


class ElectoralSystem(Base):
    __tablename__ = "electoral_systems"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    family: Mapped[str] = mapped_column(String(64))  # plurality, majority, proportional, mixed, ranked
    description: Mapped[str] = mapped_column(Text, default="")


class Office(Base):
    __tablename__ = "offices"
    __table_args__ = (UniqueConstraint("country_code", "key"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    country_code: Mapped[str] = mapped_column(ForeignKey("countries.code"))
    key: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(String(200))  # e.g. legislature chamber
    jurisdiction_level: Mapped[int] = mapped_column(Integer)  # admin level whose units host contests
    districted: Mapped[bool] = mapped_column(Boolean, default=True)
    total_seats: Mapped[int | None] = mapped_column(Integer)
    default_electoral_system: Mapped[str] = mapped_column(ForeignKey("electoral_systems.key"))


class DistrictPlan(Base):
    """A versioned set of district boundaries (e.g. a state's congressional map)."""

    __tablename__ = "district_plans"
    __table_args__ = (UniqueConstraint("office_id", "admin_unit_id", "name"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    office_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("offices.id"))
    admin_unit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("admin_units.id"))
    name: Mapped[str] = mapped_column(String(200))
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sources.id"))
    # identifiers_only: district codes known, boundaries not loaded (comparisons across plans disabled)
    # geometry_loaded: boundaries loaded from a registered boundary source
    boundary_status: Mapped[str] = mapped_column(String(32), default="identifiers_only")
    # Set only by a boundary source/editor that established the boundaries are identical.
    same_boundaries_as_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("district_plans.id"))
    notes: Mapped[str] = mapped_column(Text, default="")


class District(Base):
    __tablename__ = "districts"
    __table_args__ = (UniqueConstraint("plan_id", "code"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("district_plans.id"), index=True)
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(200))
    magnitude: Mapped[int] = mapped_column(Integer, default=1)
    admin_unit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("admin_units.id"))
    # GeoJSON geometry (EPSG:4326). When PostGIS is available, migration adds a
    # generated geometry column for spatial queries; GeoJSON stays the interchange format.
    geometry: Mapped[dict | None] = mapped_column(JSONB)
    geometry_source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sources.id"))
    plan: Mapped[DistrictPlan] = relationship()


class DistrictCrosswalk(Base):
    """Overlap between districts of different plans, for boundary-aware comparisons."""

    __tablename__ = "district_crosswalks"
    __table_args__ = (UniqueConstraint("from_district_id", "to_district_id", "method"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    from_district_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("districts.id"))
    to_district_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("districts.id"))
    population_share: Mapped[float] = mapped_column(Float)  # share of the *to* district's population
    method: Mapped[str] = mapped_column(String(64))  # e.g. block_population_overlay
    source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sources.id"))


class Party(Base):
    __tablename__ = "parties"
    __table_args__ = (UniqueConstraint("country_code", "key"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    country_code: Mapped[str] = mapped_column(ForeignKey("countries.code"))
    key: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    abbreviation: Mapped[str | None] = mapped_column(String(32))
    color: Mapped[str | None] = mapped_column(String(16))
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    successor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parties.id"))
    aliases: Mapped[list] = mapped_column(JSONB, default=list)  # identity resolution


class Coalition(Base):
    __tablename__ = "coalitions"
    id: Mapped[uuid.UUID] = uuid_pk()
    country_code: Mapped[str] = mapped_column(ForeignKey("countries.code"))
    name: Mapped[str] = mapped_column(String(200))
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)


class CoalitionMember(Base):
    __tablename__ = "coalition_members"
    coalition_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("coalitions.id"), primary_key=True)
    party_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parties.id"), primary_key=True)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)


class ElectionCycle(Base):
    __tablename__ = "election_cycles"
    __table_args__ = (UniqueConstraint("country_code", "key"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    country_code: Mapped[str] = mapped_column(ForeignKey("countries.code"))
    key: Mapped[str] = mapped_column(String(64))  # e.g. "2026"
    name: Mapped[str] = mapped_column(String(200))
    year: Mapped[int] = mapped_column(Integer)


ELECTION_KINDS = ("general", "primary", "runoff", "special", "special_primary", "special_runoff", "recall")


class Election(Base):
    __tablename__ = "elections"
    __table_args__ = (
        CheckConstraint(f"kind IN {ELECTION_KINDS}", name="kind"),
        UniqueConstraint("cycle_id", "kind", "election_date", "admin_unit_id"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    cycle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("election_cycles.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    election_date: Mapped[date] = mapped_column(Date)
    admin_unit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("admin_units.id"))
    timezone: Mapped[str] = mapped_column(String(64))
    date_basis: Mapped[str] = mapped_column(Text, default="")  # statute or source establishing the date
    source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sources.id"))


class Contest(Base):
    __tablename__ = "contests"
    __table_args__ = (UniqueConstraint("election_id", "office_id", "district_id", "admin_unit_id", "party_id", "seat_class"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    election_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("elections.id"), index=True)
    office_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("offices.id"), index=True)
    district_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("districts.id"))
    admin_unit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("admin_units.id"))
    party_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parties.id"))  # partisan primaries
    seat_class: Mapped[str | None] = mapped_column(String(16))  # e.g. Senate class
    name: Mapped[str] = mapped_column(String(300))
    seats: Mapped[int] = mapped_column(Integer, default=1)
    electoral_system: Mapped[str] = mapped_column(ForeignKey("electoral_systems.key"))
    is_special: Mapped[bool] = mapped_column(Boolean, default=False)
    source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sources.id"))
    ingestion_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ingestion_runs.id"))
    created_at = created_at()
    election: Mapped[Election] = relationship()
    office: Mapped[Office] = relationship()
    district: Mapped[District | None] = relationship()


class Candidate(Base):
    """A person standing for public office. Only public candidacy facts are stored."""

    __tablename__ = "candidates"
    id: Mapped[uuid.UUID] = uuid_pk()
    country_code: Mapped[str] = mapped_column(ForeignKey("countries.code"))
    full_name: Mapped[str] = mapped_column(String(300))
    external_ids: Mapped[dict] = mapped_column(JSONB, default=dict)  # e.g. {"fec": "H0XX00000"}


class Candidacy(Base):
    __tablename__ = "candidacies"
    __table_args__ = (UniqueConstraint("contest_id", "candidate_id"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    contest_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contests.id"), index=True)
    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidates.id"))
    party_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parties.id"))
    ballot_name: Mapped[str] = mapped_column(String(300))
    incumbent: Mapped[bool | None] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(String(32), default="filed")  # filed, qualified, withdrawn, nominee
    source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sources.id"))
    ingestion_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ingestion_runs.id"))
    candidate: Mapped[Candidate] = relationship()
    party: Mapped[Party | None] = relationship()


__all__ = [
    "Country",
    "AdminLevel",
    "AdminUnit",
    "ElectoralSystem",
    "Office",
    "DistrictPlan",
    "District",
    "DistrictCrosswalk",
    "Party",
    "Coalition",
    "CoalitionMember",
    "ElectionCycle",
    "Election",
    "Contest",
    "Candidate",
    "Candidacy",
    "ELECTION_KINDS",
]
