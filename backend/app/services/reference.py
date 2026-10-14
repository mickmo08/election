"""Synchronise country adapters (structure, rules, source registry) into the database.

Idempotent: safe to run on every deploy. Never deletes rows; administrator changes to a
source's operational status are preserved (only descriptive fields are refreshed).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..config import get_settings
from ..countries.base import CountryAdapter
from ..countries.registry import ADAPTERS
from ..models import (
    AdminLevel,
    AdminUnit,
    Country,
    Election,
    ElectionCycle,
    ElectoralSystem,
    Office,
    Party,
    Plan,
    Source,
)

DESCRIPTIVE_SOURCE_FIELDS = (
    "name", "publisher", "owner_team", "homepage_url", "access_method", "access_details", "access_terms",
    "license", "license_url", "permits_redistribution", "permits_text_analysis", "refresh_schedule",
    "freshness_sla_hours", "coverage", "reliability_notes", "data_kind", "adapter_key", "remediation",
    "verification", "is_synthetic",
)


def sync_sources(db: Session, adapter: CountryAdapter) -> None:
    for spec in adapter.sources():
        values = {f: getattr(spec, f) for f in DESCRIPTIVE_SOURCE_FIELDS}
        values["required_credentials"] = list(spec.required_credentials)
        existing = db.scalar(select(Source).where(Source.key == spec.key))
        if existing is None:
            db.add(Source(key=spec.key, status=spec.default_status, status_reason=spec.status_reason, **values))
        else:
            for k, v in values.items():
                setattr(existing, k, v)
    db.flush()


def sync_country(db: Session, adapter: CountryAdapter, years: list[int]) -> None:
    if adapter.is_synthetic and not get_settings().allows_synthetic_data:
        raise PermissionError("synthetic country adapters are disabled in this environment")
    db.execute(insert(Country).values(
        code=adapter.code, name=adapter.name, adapter_key=type(adapter).__name__,
        default_timezone=adapter.default_timezone, languages=list(adapter.languages),
        publication_rules=adapter.publication_rules(), is_synthetic=adapter.is_synthetic,
    ).on_conflict_do_update(index_elements=["code"], set_={
        "name": adapter.name, "publication_rules": adapter.publication_rules(), "languages": list(adapter.languages),
    }))
    for level, name in adapter.admin_levels():
        db.execute(insert(AdminLevel).values(country_code=adapter.code, level=level, name=name)
                   .on_conflict_do_nothing())
    for es in adapter.electoral_systems():
        db.execute(insert(ElectoralSystem).values(key=es.key, name=es.name, family=es.family,
                                                  description=es.description).on_conflict_do_nothing())
    sync_sources(db, adapter)
    by_code: dict[str, AdminUnit] = {
        u.code: u for u in db.scalars(select(AdminUnit).where(AdminUnit.country_code == adapter.code))
    }
    for spec in sorted(adapter.admin_units(), key=lambda s: s.level):
        unit = by_code.get(spec.code)
        if unit is None:
            unit = AdminUnit(country_code=adapter.code, level=spec.level, code=spec.code, name=spec.name,
                             abbreviation=spec.abbreviation, timezone=spec.timezone)
            db.add(unit)
            by_code[spec.code] = unit
        unit.parent_id = by_code[spec.parent_code].id if spec.parent_code else None
        db.flush()
    for o in adapter.offices():
        db.execute(insert(Office).values(
            country_code=adapter.code, key=o.key, name=o.name, body=o.body, jurisdiction_level=o.jurisdiction_level,
            districted=o.districted, total_seats=o.total_seats, default_electoral_system=o.default_electoral_system,
        ).on_conflict_do_nothing())
    for ps in adapter.parties():
        db.execute(insert(Party).values(country_code=adapter.code, key=ps.key, name=ps.name,
                                        abbreviation=ps.abbreviation, color=ps.color, aliases=list(ps.aliases))
                   .on_conflict_do_update(index_elements=["country_code", "key"],
                                          set_={"aliases": list(ps.aliases), "name": ps.name}))
    for year in years:
        cycle = db.scalar(select(ElectionCycle).where(ElectionCycle.country_code == adapter.code,
                                                      ElectionCycle.key == str(year)))
        if cycle is None:
            cycle = ElectionCycle(country_code=adapter.code, key=str(year), name=f"{adapter.name} {year}", year=year)
            db.add(cycle)
            db.flush()
        for entry in adapter.calendar(year):
            unit_id = by_code[entry.admin_unit_code].id if entry.admin_unit_code else None
            exists = db.scalar(select(Election).where(
                Election.cycle_id == cycle.id, Election.kind == entry.kind,
                Election.election_date == entry.election_date, Election.admin_unit_id.is_(unit_id)
                if unit_id is None else Election.admin_unit_id == unit_id))
            if exists is None:
                db.add(Election(cycle_id=cycle.id, kind=entry.kind, election_date=entry.election_date,
                                admin_unit_id=unit_id, timezone=adapter.default_timezone, date_basis=entry.basis))
    db.flush()


def sync_plans(db: Session) -> None:
    from ..entitlements import DEFAULT_PLANS  # noqa: PLC0415

    for p in DEFAULT_PLANS:
        db.execute(insert(Plan).values(**p).on_conflict_do_update(
            index_elements=["key"], set_={"name": p["name"], "quotas": p["quotas"], "features": p["features"]}))


def sync_all(db: Session, include_synthetic: bool | None = None) -> None:
    allow = get_settings().allows_synthetic_data if include_synthetic is None else include_synthetic
    sync_plans(db)
    for adapter in ADAPTERS.values():
        if adapter.is_synthetic and not allow:
            continue
        years = list(range(2010, 2027, 2)) if adapter.is_synthetic else [2018, 2020, 2022, 2024, 2026]
        sync_country(db, adapter, years)
