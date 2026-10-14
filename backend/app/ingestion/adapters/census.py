"""Census Bureau congressional district boundary shapefiles (zipped) -> versioned district plans."""

from __future__ import annotations

import io
import zipfile
from collections import Counter
from datetime import date

import shapefile
from sqlalchemy import select

from ...countries.us import load_states
from ...models import DistrictPlan
from ..framework import FetchedFile, Issue, RunContext, SourceAdapter, StructuralError, register
from ..loaders import Resolver

MAX_UNCOMPRESSED = 600 * 1024 * 1024  # zip-bomb guard


class CensusCdShapefileAdapter(SourceAdapter):
    key = "census_cd_shapefile"
    version = "1.0.0"
    schema_version = "census-cb-cd-shapefile-v1"

    def process(self, ctx: RunContext, files: list[FetchedFile]) -> None:
        congress = int(ctx.params["congress"])  # e.g. 119
        valid_from = date.fromisoformat(ctx.params["valid_from"])
        valid_to = date.fromisoformat(ctx.params["valid_to"]) if ctx.params.get("valid_to") else None
        field = f"CD{congress}FP"
        r = Resolver(ctx, "US")
        office = r.office("us_house")
        seats = {s["fips"]: int(s["house_seats_2020"]) for s in load_states()}
        for f in files:
            ref = f.filename or f.url
            try:
                zf = zipfile.ZipFile(io.BytesIO(f.content))
            except zipfile.BadZipFile as exc:
                raise StructuralError([Issue(ref, "format", "not a zip archive", blocking=True)]) from exc
            if sum(i.file_size for i in zf.infolist()) > MAX_UNCOMPRESSED:
                raise StructuralError([Issue(ref, "size", "archive expands beyond the safety limit", blocking=True)])
            names = {n.rsplit(".", 1)[-1].lower(): n for n in zf.namelist() if "/" not in n.strip("/")}
            if not {"shp", "dbf", "shx"} <= names.keys():
                raise StructuralError([Issue(ref, "format", "archive lacks .shp/.shx/.dbf", blocking=True)])
            reader = shapefile.Reader(shp=io.BytesIO(zf.read(names["shp"])), shx=io.BytesIO(zf.read(names["shx"])),
                                      dbf=io.BytesIO(zf.read(names["dbf"])))
            fields = [fd[0] for fd in reader.fields[1:]]
            if "STATEFP" not in fields or field not in fields:
                raise StructuralError([Issue(ref, "schema", f"expected STATEFP and {field}; found {fields}",
                                             blocking=True)])
            counts: Counter[str] = Counter()
            for i, sr in enumerate(reader.iterShapeRecords()):
                rec = sr.record.as_dict()
                statefp, cd = rec["STATEFP"], rec[field]
                rref = f"{ref} record {i}"
                if cd in ("ZZ",):  # areas with no district (water)
                    continue
                unit = r.unit(statefp)
                if unit is None:
                    ctx.quarantine(Issue(rref, "geo_join", f"unknown STATEFP {statefp}"))
                    continue
                geom = sr.shape.__geo_interface__
                if geom.get("type") not in ("Polygon", "MultiPolygon"):
                    ctx.quarantine(Issue(rref, "geometry", f"unexpected geometry {geom.get('type')}"))
                    continue
                name = f"{congress}th Congress districts: {unit.name}"
                plan = ctx.db.scalar(select(DistrictPlan).where(DistrictPlan.office_id == office.id,
                                                                DistrictPlan.admin_unit_id == unit.id,
                                                                DistrictPlan.name == name))
                if plan is None:
                    plan = DistrictPlan(office_id=office.id, admin_unit_id=unit.id, name=name, valid_from=valid_from,
                                        valid_to=valid_to, source_id=ctx.source.id, boundary_status="geometry_loaded",
                                        notes=f"Census cartographic boundary file, field {field}")
                    ctx.db.add(plan)
                    ctx.db.flush()
                code = f"{unit.abbreviation}-AL" if cd in ("00", "98") else f"{unit.abbreviation}-{int(cd):02d}"
                d = r.district(plan, code, f"{unit.name} {'at-large' if cd in ('00', '98') else f'district {int(cd)}'}",
                               unit)
                d.geometry = geom
                d.geometry_source_id = ctx.source.id
                counts[statefp] += 1
                ctx.count("districts")
            mismatches = {fp: (n, seats.get(fp)) for fp, n in counts.items()
                          if seats.get(fp) and n != seats[fp]}
            for fp, (n, expected) in mismatches.items():
                ctx.quarantine(Issue(ref, "apportionment_mismatch",
                                     f"state {fp}: {n} districts in file, {expected} apportioned",
                                     suggested_action="Check the file vintage/congress number."))
            ctx.check("district_counts_match_apportionment", not mismatches, f"{len(counts)} states checked")


register(CensusCdShapefileAdapter())
