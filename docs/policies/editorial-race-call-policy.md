# Editorial race-call policy (technical enforcement)

* The platform never declares winners automatically. Contest pages show the reported count, its status and the
  outcome *implied by the count under the electoral system* (labelled "not a call").
* Race calls are recorded only by platform operators with the `race_calls:record` permission, attributed to a
  source key listed in `ELECTION_AUTHORIZED_RACE_CALL_SOURCES` (default: `editorial-desk`), with a note stating
  the basis. Calls from other sources are not displayed. Retractions are new records; history is preserved.
* The assistant has no write path to race calls and refuses requests to call races.
* Editorial criteria for making a call (e.g. outstanding vote vs margin, recount thresholds) are an editorial
  decision outside this codebase and must be approved before election night.
