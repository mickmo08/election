# Engineering decisions and verification log

| Date | Decision / finding | Evidence |
|---|---|---|
| 2026-10-14 | Repository was empty; greenfield monorepo created | `git log` |
| 2026-10-14 | Build environment egress blocks FEC, Census, Harvard Dataverse, MIT hosts (HTTP 403 at proxy) | `curl` checks recorded in source register |
| 2026-10-14 | 2026 U.S. general election date derived by statute (2 U.S.C. 7) = 2026-11-03; confirmed by public reporting | `tests/test_country_contract.py`; web search |
| 2026-10-14 | Forecast national error was underestimated using in-sample residuals → switched to leave-one-cycle-out estimates; added seat-interval gate | `docs/evidence/forecast-eval-xs-2026.md` |
| 2026-10-14 | Synthetic generator's polls measured the wrong quantity (shock only) → fixed to measure expected national vote | commit history |
| 2026-10-14 | Model does not beat uniform-swing baseline on synthetic data → added gate; forecast correctly **blocked** | forecast evaluation |
| 2026-10-14 | Dependency scan found vulnerable starlette/python-multipart/pyjwt and postcss → upgraded/overridden; audits clean | CI `pip-audit`, `npm audit` |
| 2026-10-14 | axe found nested `<dl>` on source registry → fixed | e2e accessibility checks |
| 2026-10-14 | FORCE RLS would make owner-run dumps omit tenant rows on RDS → dedicated BYPASSRLS read-only backup role | `docs/operations/backup-restore.md` |
