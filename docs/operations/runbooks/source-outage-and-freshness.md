# Source outage and freshness breach

Alarm `*-freshness-breach` / `*-ingestion-failures`, or a source shows STALE in the registry.
1. Check the source's last runs (`/sources` → Ingestion runs) and quarantine items.
2. Upstream down: the UI already shows the source as stale with its last success time; do not substitute other
   data. Post a status note if the outage affects published views.
3. Format change (schema quarantine): compare the raw file (stored by hash) with the adapter schema; update the
   adapter + schema version + tests; re-run ingestion.
4. Credentials expired: rotate (`secret-rotation.md`), set status back to `active`.
5. Prolonged outage: set status `unavailable` with reason and remediation so it is visible to all users.
