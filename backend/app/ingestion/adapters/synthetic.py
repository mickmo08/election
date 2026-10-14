"""Deterministic generator for the fictional Synthetic Federation (XS). DEMO/TEST ONLY.

The generator emits one JSON document (stored as an immutable raw file like any other
source) which `process` then loads through the same loaders as real adapters.
All names are fictional; the source is flagged is_synthetic and refused in production.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import numpy as np

from ...countries.synthetic import REGIONS, synthetic_election_day
from ...models import District, DistrictCrosswalk, DistrictPlan, Source, TopicLabel
from ...services.issues import ensure_taxonomy
from ..framework import FetchedFile, RunContext, SourceAdapter, register
from ..loaders import Resolver
from ..results_writer import Line, write_snapshot

CYCLES = list(range(2010, 2027, 2))
PARTIES = ["HA", "MP", "LM"]
FIRST = [
    "Ari",
    "Bex",
    "Cato",
    "Dara",
    "Emi",
    "Fen",
    "Gil",
    "Hana",
    "Ivo",
    "Juno",
    "Kai",
    "Lior",
    "Mika",
    "Noor",
    "Oren",
    "Pia",
    "Quin",
    "Rhea",
    "Sol",
    "Tam",
    "Uma",
    "Vey",
    "Wren",
    "Yara",
    "Zev",
]
LAST = [
    "Alder",
    "Brook",
    "Cliff",
    "Dune",
    "Ember",
    "Fjord",
    "Glen",
    "Heath",
    "Isle",
    "Jade",
    "Kestrel",
    "Lark",
    "Moss",
    "Nettle",
    "Oak",
    "Pike",
    "Quarry",
    "Reed",
    "Sable",
    "Thorn",
    "Vale",
    "Willow",
]
TOPIC_SNIPPETS = {
    "economy": [
        "Families say grocery prices and inflation are squeezing budgets.",
        "La inflación y el costo de vida " "preocupan a los hogares.",
        "Local employers report hiring slowdowns and wages lag prices.",
    ],
    "housing": [
        "Rent increases and mortgage costs dominate the housing debate.",
        "El alquiler sube y la vivienda " "es inalcanzable para muchos.",
    ],
    "health": [
        "Hospital closures raise questions about health care access.",
        "Los costos de salud y medicamentos " "siguen subiendo.",
    ],
    "public_safety": [
        "Police and community groups discuss public safety plans after a rise in crime.",
        "La seguridad pública y la violencia son temas del debate.",
    ],
    "democracy": [
        "Election officials outline mail ballots procedures and certification timelines.",
        "Redistricting maps were challenged in court over gerrymander claims.",
    ],
    "climate": [
        "Wildfire season and drought put climate and energy policy on the agenda.",
        "La sequía y los incendios ponen el clima en la agenda.",
    ],
    "education": ["Teachers and schools face budget cuts; student loans remain a concern."],
    "immigration": ["Border policy and asylum processing draw attention.", "La frontera y el asilo generan debate."],
}
# Paraphrases the lexicon does not contain (so the evaluation is not trivially perfect).
PARAPHRASES = {
    "economy": "Shoppers are paying more at the checkout than a year ago.",
    "housing": "Young couples cannot afford a place of their own.",
    "health": "Clinics report long waits for appointments.",
    "public_safety": "Neighbours worry about break-ins on their street.",
}
DISTRACTORS = [
    "The weather was mild and the market square was busy.",
    "A local team won the regional final.",
    "Officials opened a new library branch downtown.",
]


def _rect(x0: float, y0: float, x1: float, y1: float) -> dict:
    return {"type": "Polygon", "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}


def generate(seed: int = 7, today: date | None = None) -> dict:
    rng = np.random.default_rng(seed)
    today = today or date(2026, 10, 14)
    districts = []
    # Regions laid out left-to-right; each region's districts stacked in a column grid.
    x = 0.0
    for code, _name, abbr, seats in REGIONS:
        cols = 2 if seats > 4 else 1
        for i in range(seats):
            c, r = i % cols, i // cols
            lean = float(rng.normal(0, 0.13))
            districts.append(
                {
                    "region": code,
                    "abbr": abbr,
                    "code": f"{abbr}-{i + 1:02d}",
                    "lean": lean,
                    "geom": _rect(x + c, r, x + c + 1, r + 1),
                    "registered": int(rng.integers(380e3, 720e3)),
                }
            )
        x += cols + 0.25
    # 2022 redistricting in Centralia: leans shift; boundaries change (crosswalk provided).
    for d in districts:
        d["lean_2022"] = d["lean"] + (float(rng.normal(0, 0.06)) if d["region"] == "05" else 0.0)
        if d["region"] == "05":
            g = d["geom"]["coordinates"][0]
            d["geom_2022"] = _rect(g[0][0], g[0][1] + 0.3, g[1][0], g[2][1] + 0.3)
    national = {y: float(rng.normal(0, 0.045)) for y in CYCLES}
    cycles = []
    incumbents = {d["code"]: ("HA" if d["lean"] > 0 else "MP") for d in districts}
    names: dict[tuple, str] = {}

    def person(key: tuple) -> str:
        if key not in names:
            names[key] = f"{FIRST[int(rng.integers(len(FIRST)))]} {LAST[int(rng.integers(len(LAST)))]}"
        return names[key]

    for y in CYCLES:
        upcoming = synthetic_election_day(y) > today
        assembly = []
        expected = []  # expected national margin (what a generic-ballot poll measures)
        for d in districts:
            lean = d["lean_2022"] if y >= 2022 else d["lean"]
            inc = incumbents[d["code"]]
            expected.append(lean + national[y] + (0.03 if inc == "HA" else -0.03))
            margin = expected[-1] + float(rng.normal(0, 0.035))
            third = float(rng.uniform(0.03, 0.10))
            turnout = float(rng.uniform(0.45, 0.66))
            total = int(d["registered"] * turnout)
            votes = {
                "HA": int(total * (1 - third) * (1 + margin) / 2),
                "MP": int(total * (1 - third) * (1 - margin) / 2),
            }
            votes["LM"] = max(0, total - votes["HA"] - votes["MP"])
            # Incumbent candidates persist with their party; open seats get new names.
            cands = {p: person((d["code"], p, y if p != inc else "inc")) for p in PARTIES}
            entry = {
                "district": d["code"],
                "region": d["region"],
                "incumbent_party": inc,
                "candidates": cands,
                "registered": d["registered"],
            }
            if not upcoming:
                entry["votes"] = votes
                winner = max(votes, key=votes.get)  # type: ignore[arg-type]
                if winner != inc:
                    names.pop((d["code"], winner, "inc"), None)
                    names[(d["code"], winner, "inc")] = cands[winner]
                incumbents[d["code"]] = winner
            assembly.append(entry)
        polls = []
        eday = synthetic_election_day(y)
        house = {
            "Northwind Research": 0.01,
            "Lumen Polling": -0.015,
            "Panelbase Online": 0.0,
            "Civic Sample Lab": 0.005,
        }
        for k in range(12):
            end = eday - timedelta(days=int(rng.integers(3, 90)))
            if end > today:
                continue
            pollster = list(house)[k % 4]
            n = int(rng.integers(600, 2200))
            prob = pollster != "Panelbase Online"
            m = float(np.mean(expected)) + house[pollster] + float(rng.normal(0, 1 / np.sqrt(n)))
            third = float(rng.uniform(0.05, 0.09))
            und = float(rng.uniform(0.04, 0.12))
            ha = round(100 * (1 - third - und) * (1 + m) / 2, 1)
            mp = round(100 * (1 - third - und) * (1 - m) / 2, 1)
            polls.append(
                {
                    "pollster": pollster,
                    "field_start": (end - timedelta(days=4)).isoformat(),
                    "field_end": end.isoformat(),
                    "population": ["rv", "lv"][k % 2],
                    "n": n,
                    "mode": "online opt-in panel" if not prob else ["live phone", "text-to-web", "mixed mode"][k % 3],
                    "sampling": "probability" if prob else "nonprobability",
                    "moe": round(100 * 1.96 * np.sqrt(0.25 / n) * 1.2, 1) if prob else None,
                    "tracking_series": "Panelbase weekly tracker" if not prob else None,
                    "results": {"HA": ha, "MP": mp, "LM": round(100 * third, 1), "Undecided": round(100 * und, 1)},
                }
            )
        cycles.append(
            {
                "year": y,
                "election_day": eday.isoformat(),
                "national_environment": national[y],
                "upcoming": upcoming,
                "assembly": assembly,
                "generic_ballot_polls": polls,
            }
        )
    # Documents: last 12 weeks before `today`.
    docs = []
    topic_keys = list(TOPIC_SNIPPETS)
    weights = np.array([5, 3, 3, 2, 2, 2, 1, 2], dtype=float)
    for i in range(700):
        published = datetime.combine(today, datetime.min.time(), UTC) - timedelta(hours=int(rng.integers(1, 84 * 24)))
        k = int(rng.integers(1, 3))
        chosen = list(rng.choice(topic_keys, size=k, replace=False, p=weights / weights.sum()))
        parts, truth = [], {}
        for t in chosen:
            if t in PARAPHRASES and rng.random() < 0.25:
                parts.append(PARAPHRASES[t])
            else:
                snippets = TOPIC_SNIPPETS[t]
                parts.append(snippets[int(rng.integers(len(snippets)))])
                parts.append(snippets[int(rng.integers(len(snippets)))])
            truth[t] = True
        parts.append(DISTRACTORS[int(rng.integers(len(DISTRACTORS)))])
        region = REGIONS[int(rng.integers(len(REGIONS)))]
        who = f"{FIRST[int(rng.integers(len(FIRST)))]} {LAST[int(rng.integers(len(LAST)))]}"
        parts.insert(
            0,
            f"In {region[1]}, resident {who} spoke at a meeting attended by {int(rng.integers(12, 900))} "
            f"people on day {int(rng.integers(1, 365))} of the session, number {i}.",
        )
        parts.append(f"Reporter note {i}: follow-up interviews are planned with {int(rng.integers(2, 40))} groups.")
        body = " ".join(parts)
        docs.append(
            {
                "external_id": f"xs-doc-{i}",
                "kind": "news" if i % 3 else "public_discussion",
                "title": f"Synthetic bulletin {i}",
                "body": body,
                "published_at": published.isoformat(),
                "country": "XS",
                "admin_unit": region[0] if rng.random() < 0.7 else None,
                "truth": truth,
            }
        )
        if rng.random() < 0.1:  # syndicated copy with trivial edits
            docs.append(
                {
                    **docs[-1],
                    "external_id": f"xs-doc-{i}-syn",
                    "title": docs[-1]["title"] + " (syndicated)",
                    "body": body + " Reporting by staff.",
                }
            )
    return {
        "seed": seed,
        "generated_for": today.isoformat(),
        "synthetic": True,
        "districts": districts,
        "cycles": cycles,
        "documents": docs,
    }


class SyntheticAdapter(SourceAdapter):
    key = "synthetic_xs"
    version = "1.0.0"
    schema_version = "synthetic-xs-v1"

    def fetch(self, source: Source, params: dict) -> list[FetchedFile]:
        data = generate(int(params.get("seed", 7)))
        return [
            FetchedFile(
                "synthetic://xs",
                json.dumps(data, sort_keys=True).encode(),
                "application/json",
                filename=f"synthetic-xs-seed{data['seed']}.json",
            )
        ]

    def process(self, ctx: RunContext, files: list[FetchedFile]) -> None:
        if not ctx.source.is_synthetic:
            raise PermissionError("synthetic adapter may only run against a synthetic source")
        data = json.loads(files[0].content)
        raw = ctx.raw_file_for(files[0])
        r = Resolver(ctx, "XS")
        assembly = r.office("xs_assembly")
        senate = r.office("xs_senate")
        units = {code: r.unit(code) for code, *_ in REGIONS}
        # --- versioned plans: 2010 plan, 2022 plan (Centralia redrawn, others identical) ---
        plans_old, plans_new = {}, {}
        for code, name, *_ in REGIONS:
            u = units[code]
            for label, store, vf, vt in (
                ("2010", plans_old, date(2010, 1, 1), date(2021, 12, 31)),
                ("2022", plans_new, date(2022, 1, 1), None),
            ):
                p = (
                    ctx.db.query(DistrictPlan)
                    .filter_by(office_id=assembly.id, admin_unit_id=u.id, name=f"{name} assembly plan {label}")
                    .one_or_none()
                )
                if p is None:
                    p = DistrictPlan(
                        office_id=assembly.id,
                        admin_unit_id=u.id,
                        name=f"{name} assembly plan {label}",
                        valid_from=vf,
                        valid_to=vt,
                        source_id=ctx.source.id,
                        boundary_status="geometry_loaded",
                        notes="SYNTHETIC",
                    )
                    ctx.db.add(p)
                    ctx.db.flush()
                store[code] = p
            if code != "05":
                plans_new[code].same_boundaries_as_id = plans_old[code].id
        dmap: dict[tuple[str, str], District] = {}
        for d in data["districts"]:
            u = units[d["region"]]
            for era, plans, geom in (("old", plans_old, d["geom"]), ("new", plans_new, d.get("geom_2022", d["geom"]))):
                dist = r.district(plans[d["region"]], d["code"], f"{u.name} {d['code']}", u)
                dist.geometry = geom
                dist.geometry_source_id = ctx.source.id
                dmap[(era, d["code"])] = dist
        # Centralia crosswalk (old -> new), overlap shares from the synthetic geometry shift.
        for d in data["districts"]:
            if d["region"] == "05":
                exists = (
                    ctx.db.query(DistrictCrosswalk)
                    .filter_by(from_district_id=dmap[("old", d["code"])].id, to_district_id=dmap[("new", d["code"])].id)
                    .first()
                )
                if not exists:
                    ctx.db.add(
                        DistrictCrosswalk(
                            from_district_id=dmap[("old", d["code"])].id,
                            to_district_id=dmap[("new", d["code"])].id,
                            population_share=0.7,
                            method="synthetic_area_overlay",
                            source_id=ctx.source.id,
                        )
                    )
        ctx.db.flush()
        # --- elections, contests, candidacies, results ---
        for cyc in data["cycles"]:
            y = cyc["year"]
            eday = date.fromisoformat(cyc["election_day"])
            election = r.election(y, "general", eday, "UTC", "Fictional rule: first Sunday of December")
            region_party_votes: dict[str, dict[str, int]] = {}
            for a in cyc["assembly"]:
                era = "new" if y >= 2022 else "old"
                dist = dmap[(era, a["district"])]
                u = units[a["region"]]
                contest = r.contest(
                    election, assembly, f"Assembly {a['district']} ({y})", "fptp", district=dist, unit=u
                )
                lines = []
                for p in PARTIES:
                    party = r.party(p, a["district"])
                    cand = r.candidate(a["candidates"][p], u)
                    cy = r.candidacy(
                        contest,
                        cand,
                        a["candidates"][p],
                        party,
                        incumbent=(p == a["incumbent_party"]),
                        status="on_ballot",
                    )
                    if "votes" in a:
                        lines.append(Line(a["candidates"][p], a["votes"][p], p, cy))
                        region_party_votes.setdefault(a["region"], {}).setdefault(p, 0)
                        region_party_votes[a["region"]][p] += a["votes"][p]
                if lines:
                    self._snapshots(ctx, contest, lines, eday, raw.id, y, a["registered"], a["district"])
            for code, pv in region_party_votes.items():
                u = units[code]
                contest = r.contest(election, senate, f"Senate list, {u.name} ({y})", "list_pr_dhondt", unit=u, seats=4)
                lines = [Line(f"{p} list", v, p) for p, v in pv.items()]
                write_snapshot(
                    ctx,
                    contest,
                    status="certified",
                    lines=lines,
                    retrieved_at=datetime.combine(eday + timedelta(days=21), datetime.min.time(), UTC),
                    raw_file_id=raw.id,
                    record_ref=f"senate {code} {y}",
                )
            for pl in cyc["generic_ballot_polls"]:
                self._poll(ctx, r, raw.id, pl, y)
        self._documents(ctx, data["documents"], raw.id)
        ctx.check("synthetic", True, f"fictional data generated with seed {data['seed']}")

    def _snapshots(self, ctx, contest, lines, eday, raw_id, year, registered, ref) -> None:  # type: ignore[no-untyped-def]
        base = datetime.combine(eday, datetime.min.time(), UTC) + timedelta(hours=20)
        total = sum(ln.votes for ln in lines)
        if year == 2024:  # successive snapshots to demonstrate results monitoring
            for pct, hours, status in ((38.0, 1, "preliminary"), (81.0, 4, "preliminary"), (100.0, 30, "unofficial")):
                partial = [
                    Line(
                        ln.label,
                        int(ln.votes * pct / 100 * (1 + 0.02 * (i - 1) * (pct < 100))),
                        ln.party_label,
                        ln.candidacy,
                    )
                    for i, ln in enumerate(lines)
                ]
                write_snapshot(
                    ctx,
                    contest,
                    status=status,
                    lines=partial,
                    retrieved_at=base + timedelta(hours=hours),
                    raw_file_id=raw_id,
                    record_ref=ref,
                    source_as_of=base + timedelta(hours=hours - 0.2),
                    reporting_pct=pct,
                    reporting_supported=True,
                    total_votes=sum(p.votes for p in partial),
                )
        write_snapshot(
            ctx,
            contest,
            status="certified",
            lines=lines,
            retrieved_at=base + timedelta(days=20),
            raw_file_id=raw_id,
            record_ref=ref,
            source_as_of=base + timedelta(days=19),
            total_votes=total,
            eligible=registered,
            denominator_kind="registered",
        )
        if year == 2024 and ref in ("NM-03", "EV-02"):
            corrected = [
                Line(ln.label, ln.votes + (137 if i == 0 else -12), ln.party_label, ln.candidacy)
                for i, ln in enumerate(lines)
            ]
            status = "corrected" if ref == "NM-03" else "recount"
            write_snapshot(
                ctx,
                contest,
                status=status,
                lines=corrected,
                retrieved_at=base + timedelta(days=34),
                raw_file_id=raw_id,
                record_ref=ref,
                source_as_of=base + timedelta(days=33),
                correction_note="Amended canvass: one precinct transposition corrected"
                if status == "corrected"
                else "Recount requested by candidate; recount totals",
                eligible=registered,
                denominator_kind="registered",
            )

    def _poll(self, ctx, r, raw_id, pl, year) -> None:  # type: ignore[no-untyped-def]
        from ...models import Poll, PollQuestion, PollResult, Pollster  # noqa: PLC0415

        pollster = ctx.db.query(Pollster).filter_by(name=pl["pollster"] + " (fictional)").one_or_none()
        if pollster is None:
            pollster = Pollster(name=pl["pollster"] + " (fictional)", transparency_notes="SYNTHETIC")
            ctx.db.add(pollster)
            ctx.db.flush()
        poll = Poll(
            pollster_id=pollster.id,
            country_code="XS",
            question_scope="generic_ballot",
            field_start=date.fromisoformat(pl["field_start"]),
            field_end=date.fromisoformat(pl["field_end"]),
            population=pl["population"],
            sample_size=pl["n"],
            mode=pl["mode"],
            sampling_method=pl["sampling"],
            weighting="SYNTHETIC: raked to age, sex, region",
            methodology_url="https://example.invalid/synthetic",
            published_moe=pl["moe"],
            tracking_series=pl["tracking_series"],
            source_id=ctx.source.id,
            raw_file_id=raw_id,
        )
        ctx.db.add(poll)
        ctx.db.flush()
        q = PollQuestion(
            poll_id=poll.id,
            wording="If the Assembly election were held today, which party would you " "vote for? (SYNTHETIC)",
            topic="vote_intention",
        )
        ctx.db.add(q)
        ctx.db.flush()
        for choice, pct in pl["results"].items():
            party = r.party(choice, "poll") if choice in PARTIES else None
            ctx.db.add(PollResult(question_id=q.id, choice=choice, party_id=party.id if party else None, pct=pct))
        ctx.count("polls")

    def _documents(self, ctx, docs, raw_id) -> None:  # type: ignore[no-untyped-def]
        from ...models import Document  # noqa: PLC0415
        from ...services.issues import content_hash, detect_languages, jaccard_estimate, minhash  # noqa: PLC0415

        topics, _ = ensure_taxonomy(ctx.db)
        r = Resolver(ctx, "XS")
        seen: list[tuple] = []
        hashes: dict[str, object] = {}
        for i, d in enumerate(docs):
            if ctx.db.query(Document.id).filter_by(source_id=ctx.source.id, external_id=d["external_id"]).first():
                continue
            text = f"{d['title']}. {d['body']}"
            lang, props = detect_languages(text)
            ch, sig = content_hash(d["body"]), minhash(d["body"])  # body only: headlines get rewritten
            dup = hashes.get(ch)
            published = datetime.fromisoformat(d["published_at"])
            if dup is None:
                for did, other, pub in seen:
                    if abs((pub - published).days) <= 3 and jaccard_estimate(sig, other) >= 0.8:
                        dup = did
                        break
            unit = r.unit(d["admin_unit"]) if d.get("admin_unit") else None
            doc = Document(
                source_id=ctx.source.id,
                external_id=d["external_id"],
                kind=d["kind"],
                url=None,
                title=d["title"],
                body=d["body"],
                published_at=published,
                language=lang,
                languages_detected=props,
                country_code="XS",
                admin_unit_id=unit.id if unit else None,
                geo_confidence="high" if unit else "none",
                content_hash=ch,
                minhash=sig,
                duplicate_of_id=dup,
                raw_file_id=raw_id,
            )
            ctx.db.add(doc)
            ctx.db.flush()
            if dup is None:
                hashes[ch] = doc.id
                seen.append((doc.id, sig, published))
                if i % 4 == 0:  # labeled evaluation subset (generator truth; synthetic)
                    for key, topic in topics.items():
                        ctx.db.add(
                            TopicLabel(
                                document_id=doc.id,
                                topic_id=topic.id,
                                is_relevant=bool(d["truth"].get(key)),
                                reviewer="synthetic-generator",
                                split="eval",
                            )
                        )
            ctx.count("duplicates" if dup else "documents")


register(SyntheticAdapter())
