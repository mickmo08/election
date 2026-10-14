# Identity resolution

* **Parties**: resolved by canonical key, name, abbreviation or alias after normalization (case, punctuation,
  `&`→`AND`). Country adapters declare canonical parties and aliases (e.g. `DFL`, `DEMOCRATIC-NPL` → Democratic).
  Unknown labels create a *provisional* party (`prov_*`) and a `party_unresolved` warning in quarantine for a
  data steward to map or confirm. Parties have validity periods and successor links for mergers/renames.
* **Candidates**: resolved by a publisher identifier when available (FEC candidate ID, or the
  `external_candidate_id` column of normalized results). Without an identifier, matching is limited to the same
  country + first-level unit + normalized name and is recorded as `match_basis = name_within_admin_unit`, so
  name collisions across states can never merge. Cross-source linking without shared IDs is a steward task.
* **Fusion tickets** (e.g. New York): one candidate across party lines is aggregated to a single candidacy; the
  line with the most votes determines the displayed party, and per-line totals remain in the raw file.
* **Districts**: codes are identifiers within a *plan*; the same code in two plans is not assumed to be the same
  place (see boundary compatibility in `docs/methodology/historical-comparison.md`).
