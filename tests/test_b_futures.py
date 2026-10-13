"""Tests for the index future, the seasonal forecast and the backtest.

The important one is `test_backtest_has_no_look_ahead`: the whole claim of the
backtest is that the model for a season was built without seeing it.
"""
import numpy as np
import pandas as pd
import pytest

from src.a_rainfall.indices import build_city_index
from src.b_bonds import forecast as F
from src.b_bonds.futures import (FuturesModel, backtest, expiry_date, monthly_contracts,
                                 spot_series)


def synthetic_index(years=range(1981, 2026), daily_mm=10.0, bump=None):
    idx = pd.date_range(f"{min(years)}-01-01", f"{max(years)}-12-31")
    frame = pd.DataFrame({"rain_mm": np.full(len(idx), daily_mm)}, index=idx)
    frame.index.name = "date"
    frame["source_group"] = "imd_grid"
    frame["is_provisional"] = False
    if bump:
        year, extra = bump
        frame.loc[f"{year}-07-01":f"{year}-07-10", "rain_mm"] = daily_mm + extra
    return build_city_index("mumbai", frame)


def climate_frame(years, nino=0.0, dmi=0.0, seed=0):
    rng = np.random.default_rng(seed)
    ys = list(years)
    return pd.DataFrame({
        "year": ys,
        "nino34": nino if np.ndim(nino) else rng.normal(nino, 1.0, len(ys)),
        "dmi": dmi if np.ndim(dmi) else rng.normal(dmi, 0.5, len(ys)),
    })


# --------------------------------------------------------------------------- future

def test_spot_ends_the_season_at_the_realised_total():
    """The exchange's identity: anchor + CDR = seasonal rainfall."""
    ci = synthetic_index(bump=(2024, 30.0))
    spot = spot_series(ci, 2024)
    assert spot.iloc[-1] == pytest.approx(ci.anchor_mm + ci.table.loc[2024, "CDR"], rel=1e-9)
    assert spot.iloc[-1] == pytest.approx(ci.table.loc[2024, "SEAS_TOTAL"], rel=1e-9)


def test_climatology_makes_the_future_a_martingale():
    """factor = 1, lambda = 0 => fair value is the spot, at every valuation date."""
    ci = synthetic_index(bump=(2024, 30.0))
    model = FuturesModel(ci, forecast_factor=1.0, risk_lambda=0.0)
    expiry = pd.Timestamp("2024-09-30")
    for asof in pd.date_range("2024-06-01", "2024-09-30", freq="15D"):
        res = model.fair_value(2024, asof, expiry)
        assert res["fair_value_mm"] == pytest.approx(res["spot_mm"], abs=1e-9)


def test_forecast_factor_moves_the_price_by_the_remaining_normal():
    ci = synthetic_index()
    base = FuturesModel(ci, forecast_factor=1.0)
    tilted = FuturesModel(ci, forecast_factor=1.10)
    asof, expiry = pd.Timestamp("2024-07-15"), pd.Timestamp("2024-09-30")
    a = base.fair_value(2024, asof, expiry)
    b = tilted.fair_value(2024, asof, expiry)
    assert b["fair_value_mm"] - a["fair_value_mm"] == pytest.approx(0.10 * a["remaining_normal_mm"])


def test_risk_premium_scales_with_the_remaining_standard_deviation():
    ci = synthetic_index(bump=(2024, 30.0))
    asof, expiry = pd.Timestamp("2024-07-15"), pd.Timestamp("2024-09-30")
    flat = FuturesModel(ci, risk_lambda=0.0).fair_value(2024, asof, expiry)
    loaded = FuturesModel(ci, risk_lambda=0.5).fair_value(2024, asof, expiry)
    assert loaded["fair_value_mm"] - flat["fair_value_mm"] == pytest.approx(
        0.5 * flat["remaining_sd_mm"])


def test_expiry_is_the_last_day_of_the_contract_month():
    assert expiry_date(2026, 6) == pd.Timestamp("2026-06-30")
    assert expiry_date(2026, 9) == pd.Timestamp("2026-09-30")
    assert expiry_date(2024, 2) == pd.Timestamp("2024-02-29")


def test_season_start_marking_prices_every_month_the_same():
    """Under climatology the expected deviation is zero whatever the horizon."""
    ci = synthetic_index(bump=(2024, 30.0))
    rows = monthly_contracts(ci, 2024, [6, 7, 8, 9], FuturesModel(ci),
                             pd.Timestamp("2024-12-31"), value_at="season_start")
    values = {round(r["fair_value_mm"], 6) for r in rows}
    assert len(values) == 1
    assert values.pop() == pytest.approx(ci.anchor_mm, abs=1e-6)


# --------------------------------------------------------------------------- forecast

def test_forecast_recovers_a_real_signal():
    """ratio = 1 + 0.2 * nino34 by construction, so the ENSO variant must win."""
    years = list(range(1981, 2026))
    rng = np.random.default_rng(1)
    nino = rng.normal(0, 1.0, len(years))
    ci = synthetic_index()
    table = ci.table.copy()
    table["SEAS_TOTAL"] = ci.anchor_mm * (1 + 0.2 * nino)
    climate = pd.DataFrame({"year": years, "nino34": nino, "dmi": np.zeros(len(years))})
    fc = F.build("x", table, climate, ci.anchor_mm)
    assert fc.selected in ("enso", "enso_iod", "enso_trend")
    assert fc.skills[fc.selected].skill_vs_climatology > 0.5
    assert fc.skills["enso"].coefficients["nino34"] == pytest.approx(0.2, abs=0.02)


def test_forecast_refuses_to_use_a_predictor_with_no_signal():
    """Pure noise must fall back to climatology rather than find a pattern."""
    years = list(range(1981, 2026))
    rng = np.random.default_rng(2)
    ci = synthetic_index()
    table = ci.table.copy()
    table["SEAS_TOTAL"] = ci.anchor_mm * (1 + rng.normal(0, 0.2, len(years)))
    climate = pd.DataFrame({"year": years, "nino34": rng.normal(0, 1, len(years)),
                            "dmi": rng.normal(0, 1, len(years))})
    fc = F.build("x", table, climate, ci.anchor_mm)
    assert fc.selected == "climatology"
    assert fc.factor({"nino34": 1.0, "dmi": 0.0}, 2026)["variant"] == "climatology"


def test_unpublished_predictor_falls_back_with_a_reason():
    years = list(range(1981, 2026))
    rng = np.random.default_rng(3)
    nino = rng.normal(0, 1.0, len(years))
    ci = synthetic_index()
    table = ci.table.copy()
    table["SEAS_TOTAL"] = ci.anchor_mm * (1 + 0.2 * nino)
    climate = pd.DataFrame({"year": years, "nino34": nino, "dmi": np.zeros(len(years))})
    fc = F.build("x", table, climate, ci.anchor_mm)
    out = fc.factor({"nino34": None, "dmi": None}, 2026)
    assert out["variant"] == "climatology"
    assert "not published" in out["reason"]


def test_backtest_has_no_look_ahead():
    """Changing a season must not change any forecast made before it.

    This is the property the whole backtest rests on, so it is tested by
    corrupting the future and checking the past does not move.
    """
    years = list(range(1981, 2026))
    rng = np.random.default_rng(4)
    nino = rng.normal(0, 1.0, len(years))
    ci = synthetic_index()
    table = ci.table.copy()
    table["SEAS_TOTAL"] = ci.anchor_mm * (1 + 0.2 * nino)
    climate = pd.DataFrame({"year": years, "nino34": nino, "dmi": np.zeros(len(years))})
    state = lambda y: {"nino34": float(climate.set_index("year")["nino34"].get(y, 0.0)),
                       "dmi": None}

    before = F.walk_forward(table, climate, ci.anchor_mm, state, 2005, 2025)
    corrupted = table.copy()
    corrupted.loc[corrupted["year"] >= 2015, "SEAS_TOTAL"] *= 3.0
    after = F.walk_forward(corrupted, climate, ci.anchor_mm, state, 2005, 2025)

    for a, b in zip(before, after):
        if a["year"] < 2015:
            assert a["factor"] == pytest.approx(b["factor"], abs=1e-12), a["year"]
    assert any(a["factor"] != pytest.approx(b["factor"]) for a, b in zip(before, after)
               if a["year"] > 2016)


def test_backtest_reports_both_models_on_the_same_seasons():
    ci = synthetic_index(bump=(2000, 20.0))
    rows = [{"year": y, "factor": 1.0, "variant": "climatology"} for y in range(1991, 2026)]
    out = backtest(ci, 1991, 2025, walk_forward_rows=rows)
    assert out["n_years"] == 35
    assert out["anchor_model"]["mae_mm"] == pytest.approx(out["forecast_model"]["mae_mm"])
    assert out["models_identical_pct"] == pytest.approx(100.0)
