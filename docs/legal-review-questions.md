# Questions for qualified legal / licensing review

Technical controls exist for each item below; none of them is a compliance determination.

1. **Source licences**: confirm terms for MEDSL Dataverse files (licence, attribution, redistribution of derived
   tables/exports), each state's results terms of use (automated access, redistribution, embargoes), Census
   boundary files (public domain — confirm for derived products), and any commercial results/polling/news feeds.
2. **Text and data mining**: which news/discussion sources permit TDM and storage of full text; jurisdiction-specific
   TDM exceptions (EU DSM Art. 3/4, UK) and opt-outs.
3. **Poll publication restrictions**: country-specific blackout periods and exit-poll embargoes to configure in
   country adapters and tenant restrictions (e.g. France, Italy, others); applicability to subscriber-only content.
4. **Survey microdata**: lawful basis and consent wording for respondent data imported by tenants; whether the
   platform is processor or controller; DPAs, sub-processors (cloud, LLM provider), cross-border transfers; special
   category data (political opinions are special category under GDPR Art. 9) even when de-identified.
5. **Political data rules**: U.S. state privacy laws and political-data provisions; restrictions on use of FEC data
   (52 U.S.C. 30111(a)(4): individual contributor information may not be used for soliciting contributions or
   commercial purposes — the platform does not ingest contributor-level data; confirm before adding it).
6. **AI-assisted content**: disclosure obligations for AI-assisted publications in target markets; provider terms
   (data retention, training use) for the configured LLM provider.
7. **Retention**: audit log retention period; deletion obligations vs backup retention; litigation holds.
8. **Race calls and forecasts**: liability and disclaimer language; election-period broadcast/publication rules
   in each launch market.
9. **Accessibility**: WCAG 2.1 AA conformance claims (automated axe checks pass on tested views; manual audit pending).
