"use client";
import { geoArea, geoMercator, geoPath, geoAlbersUsa, type GeoPermissibleObjects } from "d3-geo";
import Link from "next/link";

type Feature = { type: "Feature"; geometry: any; properties: { district: string; contest_id: string; leader: string | null;
  margin_pct: number | null; status: string | null; name: string } };

/** RFC 7946 rings are counter-clockwise; d3-geo (spherical) expects clockwise exteriors. Rewind when a
 * feature's spherical area exceeds a hemisphere, i.e. it was interpreted as "everything except this shape". */
function rewind(f: Feature): Feature {
  if (geoArea(f as any) <= 2 * Math.PI) return f;
  const g = f.geometry;
  const rev = (poly: number[][][]) => poly.map((ring) => [...ring].reverse());
  const geometry = g.type === "Polygon" ? { ...g, coordinates: rev(g.coordinates) }
    : { ...g, coordinates: g.coordinates.map(rev) };
  return { ...f, geometry };
}

export function DistrictMap({ features, colors, country }: { features: Feature[]; colors: Record<string, string>; country: string }) {
  if (!features.length) return null;
  features = features.map(rewind);
  const fc = { type: "FeatureCollection", features } as unknown as GeoPermissibleObjects;
  const W = 720, H = 360;
  const projection = (country === "US" ? geoAlbersUsa() : geoMercator()).fitSize([W, H], fc as any);
  const path = geoPath(projection);
  return (
    <figure className="chart">
      <figcaption><strong>District map</strong> <span className="muted">— shaded by leading party; opacity by margin. Each district is a
        keyboard-focusable link. A table with the same data follows the map.</span></figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="group" aria-label="District map">
        {features.map((f) => {
          const m = Math.min(Math.abs(f.properties.margin_pct ?? 0) / 30, 1);
          return (
            <Link key={f.properties.contest_id} href={`/contests/${f.properties.contest_id}`}
              aria-label={`${f.properties.district}: leader ${f.properties.leader ?? "none"}, margin ${f.properties.margin_pct ?? "n/a"} points, ${f.properties.status ?? "no results"}`}>
              <path d={path(f as any) ?? undefined} className="district"
                fill={f.properties.leader ? colors[f.properties.leader] ?? "#94a3b8" : "#e2e8f0"}
                fillOpacity={f.properties.leader ? 0.35 + 0.65 * m : 1}>
                <title>{f.properties.district}</title>
              </path>
            </Link>
          );
        })}
      </svg>
    </figure>
  );
}
