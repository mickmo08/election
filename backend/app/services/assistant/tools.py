"""Read-only analytical tools available to the assistant.

Every tool:
  * runs on the caller's RLS-scoped session (tenant isolation is enforced by the database,
    not by the model);
  * computes all numbers in backend code;
  * returns `evidence` items with a stable id, evidence kind, source attribution, freshness
    and synthetic flag, which the answer must cite.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import Contest, District, ForecastRun, Source
from .. import issues, polling, results
from ..freshness import source_freshness

INJECTION_PATTERNS = re.compile(
    r"(ignore (all |any )?(previous|prior|above) instructions|disregard .{0,30}instructions|system prompt|"
    r"you are now|act as|reveal .{0,20}(key|secret|prompt)|<\s*/?\s*(system|tool|assistant)\s*>|BEGIN PROMPT)",
    re.I,
)

EVIDENCE_KINDS = {
    "official_result": "Official or authority-published results",
    "poll": "Published survey/poll estimates",
    "model_estimate": "Platform model estimate (not an observed result)",
    "public_discussion": "Topic frequency in covered text (not population opinion)",
    "source_registry": "Data source status and freshness",
}


@dataclass
class ToolResult:
    name: str
    args: dict
    data: dict
    evidence: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class Toolbox:
    def __init__(self, db: Session, tenant_id: uuid.UUID) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self._n = 0
        self.sources = {s.id: s for s in db.scalars(select(Source))}
        self.sources_by_key = {s.key: s for s in self.sources.values()}

    def _evidence(self, kind: str, source: Source | None, summary: str, values: dict, retrieved_at=None) -> dict:  # type: ignore[no-untyped-def]
        self._n += 1
        fresh = source_freshness(source) if source else None
        return {
            "id": f"E{self._n}",
            "kind": kind,
            "kind_label": EVIDENCE_KINDS[kind],
            "source_key": source.key if source else None,
            "source_name": source.name if source else None,
            "publisher": source.publisher if source else None,
            "retrieved_at": retrieved_at,
            "is_synthetic": bool(source and source.is_synthetic),
            "stale": bool(fresh and fresh["state"] == "stale"),
            "summary": summary,
            "values": values,
        }

    # ------------------------------------------------------------------ tools
    SPECS = {
        "find_contests": {
            "description": "Find contests by country, cycle year, office key and/or region/state code "
            "or district code.",
            "params": {"country": "str", "cycle": "str", "office": "str?", "admin_unit": "str?", "district": "str?"},
        },
        "contest_results": {
            "description": "Current result snapshot, status, history and attributed race calls for " "one contest.",
            "params": {"contest_id": "uuid"},
        },
        "district_history": {
            "description": "Results across cycles for a district with boundary compatibility.",
            "params": {"district_id": "uuid"},
        },
        "polling_average": {
            "description": "Transparent polling average as of a date.",
            "params": {"country": "str", "scope": "str", "as_of": "date?"},
        },
        "forecast_status": {
            "description": "Latest forecast run (published or blocked) with gates and uncertainty.",
            "params": {"country": "str", "office": "str", "cycle": "str"},
        },
        "topic_trends": {
            "description": "Weekly topic frequency in covered news/public text (not opinion).",
            "params": {"country": "str", "weeks": "int?"},
        },
        "source_status": {"description": "Registry status and freshness for data sources.", "params": {}},
    }

    def call(self, name: str, args: dict) -> ToolResult:
        fn = getattr(self, f"t_{name}", None)
        if fn is None or name not in self.SPECS:
            raise KeyError(f"unknown tool {name}")
        return fn(**args)

    def t_find_contests(
        self,
        country: str,
        cycle: str,
        office: str | None = None,
        admin_unit: str | None = None,
        district: str | None = None,
    ) -> ToolResult:
        rows = results.list_contests(
            self.db, country=country.upper(), cycle=str(cycle), office=office, admin_unit=admin_unit, limit=1000
        )
        if district:
            rows = [r for r in rows if (r["district"] or "").upper() == district.upper()]
        return ToolResult(
            "find_contests",
            {"country": country, "cycle": cycle, "office": office, "admin_unit": admin_unit, "district": district},
            {
                "contests": [{k: r[k] for k in ("id", "name", "office", "district", "status")} for r in rows[:25]],
                "count": len(rows),
            },
        )

    def t_contest_results(self, contest_id: str) -> ToolResult:
        det = results.contest_detail(self.db, uuid.UUID(contest_id))
        if det is None:
            return ToolResult("contest_results", {"contest_id": contest_id}, {"found": False})
        res = ToolResult("contest_results", {"contest_id": contest_id}, {"found": True, "contest": det["name"]})
        cur = det["current"]
        if cur is None:
            res.warnings.append(f"No results have been published for {det['name']} by any registered source.")
            res.data["has_results"] = False
            return res
        src = self.sources_by_key.get(cur["source"]["key"]) if cur["source"] else None
        lines = cur["lines"]
        top = lines[:2]
        values = {f"{ln['label']} votes": ln["votes"] for ln in lines}
        values.update({f"{ln['label']} share": ln["share"] for ln in lines})
        if len(top) == 2 and top[0]["share"] is not None:
            values["margin_pts"] = round(top[0]["share"] - top[1]["share"], 2)
            values["margin_votes"] = top[0]["votes"] - top[1]["votes"]
        values["total_votes"] = cur["total_votes"]
        if cur["reporting_pct"] is not None:
            values["reporting_pct"] = cur["reporting_pct"]
        if cur["turnout"]:
            values["turnout_pct"] = cur["turnout"]["pct"]
        res.data.update(
            {
                "status": cur["status"],
                "status_label": cur["status_label"],
                "lines": lines,
                "values": values,
                "implied_outcome": det["implied_outcome"],
                "race_calls": det["race_calls"],
                "history_count": len(det["history"]),
                "correction_note": cur["correction_note"],
            }
        )
        res.evidence.append(
            self._evidence("official_result", src, f"{det['name']}: {cur['status_label']}", values, cur["retrieved_at"])
        )
        if cur["status"] == "preliminary":
            res.warnings.append("Results are preliminary; totals will change.")
        if cur["disputed"]:
            res.warnings.append(f"Result is disputed: {cur['dispute_note']}")
        if not det["race_calls"]:
            res.warnings.append(
                "No race call from an authorized source is recorded; the assistant does not call races."
            )
        return res

    def t_district_history(self, district_id: str) -> ToolResult:
        h = results.district_history(self.db, uuid.UUID(district_id))
        res = ToolResult("district_history", {"district_id": district_id}, {"district": h["district"], "rows": []})
        for row in h["history"]:
            comp = row["compatibility"]
            res.data["rows"].append(
                {
                    "cycle": row["cycle"],
                    "status": row["status"],
                    "comparable": comp["comparable"],
                    "basis": comp["basis"],
                    "top": row["lines"][:2],
                }
            )
            if not comp["comparable"]:
                res.warnings.append(f"{row['cycle']}: not comparable — {comp['detail']}")
        return res

    def t_polling_average(self, country: str, scope: str = "generic_ballot", as_of: str | None = None) -> ToolResult:
        d = date.fromisoformat(as_of) if as_of else datetime.now(UTC).date()
        avg = polling.average(self.db, country=country.upper(), scope=scope, as_of=d)
        res = ToolResult("polling_average", {"country": country, "scope": scope, "as_of": d.isoformat()}, avg)
        if not avg["available"]:
            res.warnings.append(f"No eligible polls for {country} {scope} in the 60 days before {d}.")
            return res
        values = {f"{k} average": v["mean"] for k, v in avg["estimates"].items()}
        values.update({f"{k} spread": v["spread_sd"] for k, v in avg["estimates"].items()})
        values["polls_included"] = avg["n_polls"]
        src = self.sources_by_key.get("xs-synthetic") if avg.get("uses_synthetic_data") else None
        ev = self._evidence("poll", src, f"Polling average ({scope}) as of {d}: {avg['method']}", values)
        ev["is_synthetic"] = avg.get("uses_synthetic_data", False)
        res.evidence.append(ev)
        res.warnings.append("Spread is the variation across polls, not a margin of error.")
        return res

    def t_forecast_status(self, country: str, office: str, cycle: str) -> ToolResult:
        q = select(ForecastRun).where(
            ForecastRun.country_code == country.upper(),
            ForecastRun.office_key == office,
            ForecastRun.cycle_key == str(cycle),
            ForecastRun.kind == "forecast",
        )
        run = self.db.scalar(q.where(ForecastRun.status == "published").order_by(ForecastRun.published_at.desc()))
        latest = run or self.db.scalar(q.order_by(ForecastRun.created_at.desc()))
        res = ToolResult("forecast_status", {"country": country, "office": office, "cycle": cycle}, {})
        if latest is None:
            res.data = {"available": False}
            res.warnings.append("No forecast run exists for this contest set.")
            return res
        failed = [g for g in latest.gate_results if not g["passed"]]
        res.data = {
            "available": latest.status == "published",
            "status": latest.status,
            "failed_gates": failed,
            "data_cutoff": latest.data_cutoff.date().isoformat(),
        }
        if latest.status != "published":
            res.warnings.append(
                "No published forecast: " + "; ".join(f"{g['gate']}: {g['detail']}" for g in failed)
                if failed
                else "Forecast not yet published."
            )
            return res
        agg = latest.aggregate_outputs
        values = {
            "seats_a_median": agg["seats_a"]["median"],
            "seats_a_p10": agg["seats_a"]["p10"],
            "seats_a_p90": agg["seats_a"]["p90"],
        }
        if agg.get("p_a_majority") is not None:
            values["p_a_majority_pct"] = round(100 * agg["p_a_majority"], 1)
        ev = self._evidence(
            "model_estimate",
            None,
            f"Forecast {latest.id} (model estimate, data cutoff " f"{latest.data_cutoff.date()})",
            values,
            latest.published_at,
        )
        ev["is_synthetic"] = latest.uses_synthetic_data
        res.evidence.append(ev)
        res.data["values"] = values
        return res

    def t_topic_trends(self, country: str, weeks: int = 8) -> ToolResult:
        end = datetime.now(UTC)
        tr = issues.topic_trends(self.db, country=country.upper(), start=end - timedelta(weeks=int(weeks)), end=end)
        res = ToolResult("topic_trends", {"country": country, "weeks": weeks}, {"coverage": tr["coverage"]})
        totals = {}
        for key, series in tr["series"].items():
            m = sum(p["mentions"] or 0 for p in series)
            d = sum(p["documents"] for p in series if not p["suppressed"])
            if d:
                totals[tr["labels"][key]] = round(100 * m / d, 1)
        top = dict(sorted(totals.items(), key=lambda kv: -kv[1])[:5])
        values = {f"{k} share_pct": v for k, v in top.items()}
        values["documents"] = tr["coverage"]["documents"]
        synthetic = any(self.sources[s].is_synthetic for s in self.sources if self.sources[s].data_kind == "synthetic")
        ev = self._evidence(
            "public_discussion",
            self.sources_by_key.get("xs-synthetic") if country.upper() == "XS" else None,
            f"Topic frequency in {tr['coverage']['documents']} de-duplicated documents over "
            f"{weeks} weeks (model {tr['model_version']})",
            values,
        )
        ev["is_synthetic"] = country.upper() == "XS" and synthetic
        res.evidence.append(ev)
        res.data["top_topics"] = top
        res.warnings.append(
            "Topic frequency reflects covered sources only; it is not a measure of public opinion "
            "or voting intention."
        )
        if tr["coverage"]["documents"] == 0:
            res.warnings.append("No licensed text sources cover this country/period.")
        return res

    def t_source_status(self) -> ToolResult:
        rows = []
        for s in self.sources.values():
            f = source_freshness(s)
            rows.append(
                {
                    "key": s.key,
                    "name": s.name,
                    "status": s.status,
                    "freshness": f["state"],
                    "reason": s.status_reason,
                    "remediation": s.remediation,
                    "synthetic": s.is_synthetic,
                }
            )
        res = ToolResult("source_status", {}, {"sources": rows})
        unavailable = [r for r in rows if r["status"] != "active"]
        values = {"sources_total": len(rows), "sources_unavailable": len(unavailable)}
        res.evidence.append(self._evidence("source_registry", None, "Source registry status", values))
        return res

    # ------------------------------------------------------------------ helpers for planners
    def resolve_district_contest(self, country: str, code: str, cycle: str | None) -> tuple[str | None, str | None]:
        q = (
            select(Contest.id, District.id)
            .join(District, District.id == Contest.district_id)
            .where(District.code == code.upper())
        )
        rows = self.db.execute(q).all()
        if not rows:
            return None, None
        if cycle:
            for cid, did in rows:
                det = results.contest_detail(self.db, cid)
                if det and det["election"]["cycle"] == str(cycle) and det["election"]["kind"] == "general":
                    return str(cid), str(did)
        return None, str(rows[-1][1])


def sanitize_untrusted(text: str) -> tuple[str, bool]:
    """Neutralise instruction-like content in retrieved documents before it reaches a model."""
    flagged = bool(INJECTION_PATTERNS.search(text))
    cleaned = INJECTION_PATTERNS.sub("[removed: instruction-like text in source document]", text)
    return cleaned[:2000], flagged
