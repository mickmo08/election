"use client";
import { useApi } from "@/lib/useApi";

export type Country = { code: string; name: string; is_synthetic: boolean; cycles: string[]; offices: { key: string; name: string }[] };

export function useCountries() {
  return useApi<Country[]>("/api/v1/countries");
}

export function CountryCycle({ countries, country, cycle, onChange, office, onOffice }: {
  countries: Country[]; country: string; cycle: string; onChange: (country: string, cycle: string) => void;
  office?: string; onOffice?: (o: string) => void;
}) {
  const c = countries.find((x) => x.code === country);
  return (
    <div className="filters">
      <label>Country
        <select value={country} onChange={(e) => {
          const next = countries.find((x) => x.code === e.target.value)!;
          onChange(next.code, next.cycles[0] ?? "");
        }}>
          {countries.map((x) => <option key={x.code} value={x.code}>{x.name}</option>)}
        </select>
      </label>
      <label>Cycle
        <select value={cycle} onChange={(e) => onChange(country, e.target.value)}>
          {c?.cycles.map((y) => <option key={y} value={y}>{y}</option>)}
        </select>
      </label>
      {onOffice && (
        <label>Office
          <select value={office} onChange={(e) => onOffice(e.target.value)}>
            <option value="">All offices</option>
            {c?.offices.map((o) => <option key={o.key} value={o.key}>{o.name}</option>)}
          </select>
        </label>
      )}
    </div>
  );
}

export const PARTY_COLORS: Record<string, string> = {
  DEM: "#2563eb", REP: "#dc2626", LIB: "#ca8a04", GRE: "#16a34a", IND: "#6b7280",
  HA: "#0f766e", MP: "#c2410c", LM: "#7c3aed",
};
