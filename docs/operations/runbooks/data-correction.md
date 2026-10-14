# Data correction

* Official results: never edit snapshots. Ingest the publisher's corrected publication with status `corrected`
  (or `recount`) and a correction note; it supersedes the previous snapshot and history remains visible.
* Our own error (adapter bug): fix the adapter, bump its version, re-run ingestion from the stored raw file; the
  new run creates new snapshots; document the correction in the source's run notes.
* Published reports: create a correction version with a correction note; it requires review before publishing.
* Forecasts: withdraw by publishing a corrected validated run (previous published run becomes `withdrawn`).
* Quarantine decisions: resolve items with `accepted | rejected | fixed` and a note (audited).
