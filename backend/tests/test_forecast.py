"""Forecast methodology guards: leakage, gating, scenarios, publication."""

from datetime import date

import pytest

from app.countries.synthetic import synthetic_election_day
from app.models import ForecastRun
from app.services.forecasting import model as M
from app.services.forecasting import service as fc
from app.services.forecasting.data import cycle_inputs


def test_inputs_never_include_information_after_cutoff(wdb):
    cut = M.cutoff_for(synthetic_election_day(2022))
    ci = cycle_inputs(wdb, country="XS", office_key="xs_assembly", year=2022, cutoff=cut)
    assert all(r.margin is None for r in ci.rows), "target outcomes must be hidden"
    for ref in ci.used["prior_results"] + ci.used["polls"]:
        assert date.fromisoformat(ref.rsplit(":", 1)[1]) < cut
    assert all(
        date.fromisoformat(p.rsplit(":", 1)[1]) <= date.fromordinal(cut.toordinal() - 1) for p in ci.used["polls"]
    )


def test_predictions_invariant_to_target_outcomes(wdb):
    """Perturbation test: changing the held-out cycle's results must not change its forecast."""
    cut = M.cutoff_for(synthetic_election_day(2022))
    cycles = fc._office_cycles(wdb, "XS", "xs_assembly")
    train = fc._training(wdb, "XS", "xs_assembly", cycles, 2022, cut)
    assert max(t.year for t in train) < 2022
    target = cycle_inputs(wdb, country="XS", office_key="xs_assembly", year=2022, cutoff=cut)
    p1 = M.predict(M.fit(train), target)
    for r in target.rows:
        r.margin = 0.99  # if anything read the truth, predictions would move
    p2 = M.predict(M.fit(train), target)
    assert [a.mean for a in p1] == [b.mean for b in p2]


@pytest.fixture(scope="module")
def run_2026():
    from app.db import worker_session

    with worker_session() as db:
        run = fc.run_forecast(
            db, country="XS", office_key="xs_assembly", cycle_year=2026, data_cutoff=None, created_by="test"
        )
        db.commit()
        return run.id


def test_gates_block_publication_honestly(wdb, run_2026):
    run = wdb.get(ForecastRun, run_2026)
    gates = {g["gate"]: g for g in run.gate_results}
    assert run.status == "blocked"
    assert gates["competitive_with_uniform_swing"]["passed"] is False  # model does not beat the simple baseline
    assert gates["beats_persistence_baseline"]["passed"] is True
    assert run.backtest["cycles"] and all(c["train_cycles"][-1] < c["cycle"] for c in run.backtest["cycles"])
    assert run.data_cutoff.date() <= date.today()
    with pytest.raises(PermissionError):
        fc.publish(wdb, run)


def test_publication_requires_all_gates(wdb, run_2026, monkeypatch):
    run = wdb.get(ForecastRun, run_2026)
    run.status = "validated"  # simulate an all-gates-pass run
    fc.publish(wdb, run)
    assert run.status == "published" and run.published_at
    wdb.rollback()


def test_scenarios_are_not_forecasts(wdb):
    s = fc.run_forecast(
        wdb,
        country="XS",
        office_key="xs_assembly",
        cycle_year=2026,
        data_cutoff=None,
        created_by="test",
        scenario={"national_environment_shift": 0.05},
    )
    assert s.kind == "scenario"
    s.status = "validated"
    with pytest.raises(PermissionError):
        fc.publish(wdb, s)
    with pytest.raises(ValueError):
        fc.run_forecast(
            wdb,
            country="XS",
            office_key="xs_assembly",
            cycle_year=2026,
            data_cutoff=None,
            created_by="t",
            scenario={"national_environment_shift": 0.9},
        )
    wdb.rollback()


def test_no_forecast_without_contests(wdb):
    run = fc.run_forecast(
        wdb, country="US", office_key="us_house", cycle_year=2026, data_cutoff=None, created_by="test"
    )
    assert run.status == "blocked" and run.gate_results[0]["gate"] == "contests_known"
    wdb.rollback()


def test_future_cutoff_rejected(wdb):
    with pytest.raises(ValueError):
        fc.run_forecast(
            wdb, country="XS", office_key="xs_assembly", cycle_year=2026, data_cutoff=date(2030, 1, 1), created_by="t"
        )


def test_unpublished_outputs_withheld_from_tenants(client, headers, run_2026):
    body = client.get(f"/api/v1/forecasts/{run_2026}", headers=headers("demo-analyst")).json()
    assert body["contest_outputs"] is None and body["aggregate_outputs"] is None and body["withheld_reason"]
    assert body["gate_results"]
    op = client.get(f"/api/v1/forecasts/{run_2026}", headers=headers("demo-admin")).json()
    assert op["aggregate_outputs"]["seats_a"]


def test_metrics_math():
    preds = [M.Prediction("a", "x", 0.1, 0.1, 0.84), M.Prediction("b", "y", -0.1, 0.1, 0.16)]
    out = {"a": 0.05, "b": -0.02}
    assert M.brier(preds, out) == pytest.approx(((0.84 - 1) ** 2 + 0.16**2) / 2)
    cal = M.calibration(preds, out)
    assert cal["ece"] is not None and len(cal["bins"]) == 2
