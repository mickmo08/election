# Country adapter contract

Adding a country requires **no schema change**: implement `app.countries.base.CountryAdapter`, register it in
`app/countries/registry.py`, and pass the contract tests (`tests/test_country_contract.py`, parametrized over
every registered adapter).

| Member | Contract |
|---|---|
| `code`, `name`, `default_timezone`, `languages` | ISO 3166-1 alpha-2 (user-assigned `X*` codes are reserved for fictional/synthetic data) |
| `admin_levels()` | Contiguous levels from 0 (nation) |
| `admin_units()` | Unique codes; exactly one level-0 root; each parent exactly one level up; optional timezone; validity dates supported in the schema |
| `electoral_systems()` | Every system an office or rule references (`plurality`, `majority`, `proportional`, `mixed`, `ranked` families) |
| `offices()` | Office key, body, jurisdiction level, districted flag, total seats, default system |
| `electoral_system_rules()` | (office, unit, stage) overrides, each with legal citation and verification status |
| `parties()` | Canonical parties + label aliases for identity resolution |
| `calendar(year)` | **Only dates fixed by rule**, each with a citation. Administratively set dates (primaries, runoffs, specials) must come from sources |
| `sources()` | Source specs with owner, access method, terms, licence, refresh, coverage, reliability, status + remediation when unavailable |
| `result_status_map` | Publisher status labels → canonical `preliminary | unofficial | certified | corrected | recount`; unknown labels are quarantined |
| `publication_rules()` | E.g. poll blackout days, embargo rules; enforced at report publication |

Multi-member districts (`contests.seats`, `districts.magnitude`), list PR (`list_pr_dhondt` with D'Hondt
allocation in the results service), two-round systems (runoff elections as separate `elections` of kind
`runoff`), ranked-choice (flagged as requiring authority tabulation) and partisan primaries (`contests.party_id`)
are covered by the core model; the fictional XS adapter exercises FPTP, list PR and two-round systems.

## Worked example: adding the United Kingdom (outline)
1. `GB` adapter: levels (UK, nation, local authority); offices `uk_commons` (650, FPTP); parties with aliases
   (e.g. "Lab", "Labour Co-op" → Labour with coalition/affiliation notes); calendar returns `[]` (no fixed date
   since the Dissolution and Calling of Parliament Act 2022 — dates come from an editorial/official source);
   publication rules (exit-poll embargo until polls close); sources: Electoral Commission results, Ordnance Survey
   Boundary-Line (OGL), House of Commons Library results datasets.
2. Mappers from those publishers' files into `official_results_csv` / boundary loaders.
3. Run the contract tests; add fixture-based adapter tests; register sources; nothing else changes.
