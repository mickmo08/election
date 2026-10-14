# Polling and survey methodology

* Stored per poll: pollster, sponsor (+ partisan flag), field dates, population (all adults / registered /
  likely / voters), sample size, mode, sampling method, weighting description, methodology and questionnaire
  links, question wording, results by subgroup, tracking series, published MOE, design effect.
* **Uncertainty**: probability samples show the published MOE; if absent, an approximate MOE assuming simple
  random sampling (inflated by a published design effect) labelled as approximate. Nonprobability or unknown
  designs show **no margin of error**, even if the pollster published one (stored, flagged in quarantine).
* **Average**: exponential recency weights (half-life 14 days) × √n (capped at 3,000) × population weight
  (LV/V 1.0, RV 0.85, adults 0.6) × 0.5 for partisan sponsors, over a 60-day window ending at `as_of`. The
  reported spread is the weighted SD across polls — explicitly not a margin of error.
* **Overlapping samples**: within a tracking series, releases whose field periods overlap share respondents;
  the most recent non-overlapping set is used and exclusions are listed.
* **Survey microdata** (tenant-private): consent basis and de-identification attestation required; direct and
  quasi-identifier columns (names, emails, phones, addresses, ZIP, DOB, IDs, coordinates) and identifier-like
  values are rejected; weights validated; aggregates suppress cells with n < 30 plus complementary suppression;
  bases reported in bands; every aggregate request is audited.
