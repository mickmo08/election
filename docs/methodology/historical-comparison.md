# Historical comparison and boundary compatibility

Each district belongs to a versioned plan (`district_plans`) with `boundary_status`:
`identifiers_only` (codes known from results/filings; boundaries not loaded) or `geometry_loaded`.

`compatibility(a, b)` returns:
* `same_district` / `identical_boundaries` — same plan, or plans linked by `same_boundaries_as` (set only by a
  boundary source or editor who established identity) → comparable;
* `crosswalk` — a population crosswalk exists; comparable when overlap ≥ 60%, shown with the share;
* `unknown` — otherwise **not comparable**, with the reason (boundaries not loaded / no crosswalk).

Historical charts include only comparable cycles; tables list every cycle with its compatibility verdict.
Results loaded without boundaries create a per-year `identifiers_only` plan, so comparisons across years stay
disabled until boundaries or a crosswalk are loaded. This matters for 2026: several U.S. states use maps enacted
after the most recent Census boundary files, and those plans must come from state redistricting sources.
