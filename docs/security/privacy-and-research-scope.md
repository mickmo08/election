# Privacy and research scope

**In scope:** aggregate election results, geography, published polls, consent-based de-identified survey
aggregates, aggregate topic frequency in licensed/permitted text, documented statistical forecasts.

**Out of scope (enforced):**
| Rule | Enforcement |
|---|---|
| No inference about a named person's beliefs, religion, ethnicity or vote | Assistant policy refusals (`services/assistant/policy.py`); no person-level opinion data model; candidates store only public candidacy facts |
| No persuasion, ad targeting or voter outreach | Policy refusals; no contact data stored; survey imports reject identifiers |
| Turnout ≠ ballot choice | Policy refusal; no voter-file ingestion adapter exists |
| Official results, surveys, online discussion and model estimates kept distinct | Separate tables/endpoints; evidence `kind` on every assistant citation; UI labels |
| Online text is not representative opinion | Issues view measures topic frequency only; no sentiment model; banner on every issues view |
| Respondent privacy | No row-level endpoints, suppression (n<30), complementary suppression, base bands, identifier rejection, consent and de-identification attestations recorded, audit on every aggregate |
| Author privacy in public discussion | Items with author/user/handle fields are rejected at ingestion |

**Retention**: tenant `data_retention_days` purges assistant logs and export records; usage events after 800
days; tenant offboarding purges all tenant data (runbook). Raw source files are retained under Object Lock.

Applicable laws (GDPR/UK GDPR for EU/UK respondents, U.S. state privacy laws, sector rules for survey vendors)
require qualified review — see `docs/legal-review-questions.md`. Technical controls are not a compliance claim.
