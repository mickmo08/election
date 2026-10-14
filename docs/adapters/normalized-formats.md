# Normalized ingestion formats

All files are UTF-8 CSV (or JSON Lines for documents). Unknown columns are ignored; required columns missing →
the whole file is quarantined (`schema`), nothing loads.

## `official_results_csv` (adapter `official_results_csv`)
One row per candidate line per contest per publication.
| Column | Required | Notes |
|---|---|---|
| country | yes | adapter code |
| election_kind | yes | general, primary, runoff, special, special_primary, special_runoff, recall |
| election_date | yes | ISO date |
| admin_unit | yes | unit code or abbreviation (e.g. `WY`, `56`) |
| office_key | yes | adapter office key |
| district | yes (may be blank) | district code for districted offices |
| candidate, party, votes | yes | votes integer ≥ 0 |
| status | yes | publisher label, mapped via the adapter status map |
| source_as_of | yes | ISO timestamp **with timezone** |
| reporting_pct | yes (may be blank) | blank = the publisher does not report completeness (never imputed) |
| writein, external_candidate_id, correction_note, primary_party, seats | no | |

Rules: one status per contest per file; duplicate candidates invalidate that contest's snapshot; certified
totals change only with `corrected`/`recount`; vote decreases between preliminary updates are flagged.

## `editorial_contests_csv`
`country, election_kind, election_date, admin_unit, office_key, district, citation_url (https, official),
verified_by, contest_name, seat_class, is_special, seats, primary_party`. Rows without a citation are rejected.

## `polls_csv`
`pollster, sponsor, sponsor_is_partisan, country, admin_unit, office_key, district, election_date,
question_scope (contest|generic_ballot|approval|issue), field_start, field_end, population (a|rv|lv|v),
sample_size, mode, sampling_method (probability|nonprobability|mixed|unknown), weighting, methodology_url
(required), questionnaire_url, published_moe, tracking_series, question_wording, choice, party, pct, subgroup, topic`.

## `documents_jsonl`
`{external_id, kind: news|public_discussion, url, title, body, published_at (tz), country, admin_unit?, language?}`.
Items with author/user fields are rejected. The source licence must permit text analysis.

## MEDSL constituency returns, OpenFEC candidates, Census CD shapefiles
Publisher formats handled by dedicated adapters (`medsl.py`, `fec.py`, `census.py`); see the source register.
