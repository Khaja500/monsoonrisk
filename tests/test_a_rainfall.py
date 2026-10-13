"""Module A acceptance tests (spec A.9)."""
import numpy as np
import pandas as pd
import pytest

from src.a_rainfall.indices import (build_city_index, choose_season_window, daily_lpa,
                                    season_mask, season_months)


def synthetic_frame(years=range(1991, 2026), daily_mm=10.0):
    idx = pd.date_range(f"{min(years)}-01-01", f"{max(years)}-12-31")
    frame = pd.DataFrame({"rain_mm": np.full(len(idx), daily_mm)}, index=idx)
    frame.index.name = "date"
    frame["source_group"] = "imd_grid"
    frame["is_provisional"] = False
    return frame


def test_season_mask_and_months():
    idx = pd.date_range("2021-01-01", "2021-12-31")
    assert season_mask(idx, "06-01", "09-30").sum() == 122
    assert season_months("06-01", "09-30") == 4
    assert season_months("12-01", "02-28") == 3


def test_lpa_of_constant_series_is_constant():
    frame = synthetic_frame()
    lpa = daily_lpa(frame["rain_mm"], 1991, 2020, 15)
    assert np.allclose(lpa.to_numpy(), 10.0)


def test_cdr_of_lpa_series_is_zero():
    """A season made of exactly the normal has zero cumulative deviation."""
    frame = synthetic_frame()
    ci = build_city_index("mumbai", frame)
    assert abs(ci.table["CDR"].mean()) < 1e-6


def test_indices_on_hand_computed_series():
    frame = synthetic_frame(years=range(1991, 2026))
    frame.loc["2024-07-01", "rain_mm"] = 100.0
    frame.loc["2024-07-02", "rain_mm"] = 50.0
    ci = build_city_index("mumbai", frame)
    row = ci.table.loc[2024]
    scale = ci.bias["imd_grid"]["factor"]
    assert row["MAX1"] == pytest.approx(100.0 * scale, rel=1e-9)
    assert row["MAX3"] == pytest.approx(160.0 * scale, rel=1e-9)   # 10 + 100 + 50
    assert row["WET_DAYS"] == 122
    assert row["SEAS_TOTAL"] == pytest.approx((122 * 10 + 90 + 40) * scale, rel=1e-9)


def test_no_negative_rain_and_completeness_flag():
    frame = synthetic_frame()
    ci = build_city_index("mumbai", frame)
    assert (ci.daily >= 0).all()
    assert ci.table["complete"].all()


def test_window_selection_prefers_fewest_months_above_share():
    idx = pd.date_range("1991-01-01", "2020-12-31")
    rain = pd.Series(0.0, index=idx)
    rain[season_mask(idx, "06-01", "09-30")] = 10.0     # all rain inside Jun-Sep
    window, table = choose_season_window(rain, [["06-01", "11-30"], ["06-01", "09-30"]],
                                         1991, 2020, min_share=0.75)
    assert window == ["06-01", "09-30"]
    assert {t["months"] for t in table} == {6, 4}


def test_peaks_over_threshold_returns_increasing_return_levels():
    """Heavier tail must give higher return levels at higher return periods."""
    import numpy as np
    from src.a_rainfall.fit import peaks_over_threshold

    rng = np.random.default_rng(11)
    idx = pd.date_range("1981-01-01", "2025-12-31")
    rain = pd.Series(rng.gamma(0.6, 8.0, len(idx)), index=idx)
    pot = peaks_over_threshold(rain, ("06-01", "09-30"), threshold_q=0.90)
    assert pot is not None
    levels = [pot["return_levels"][k] for k in sorted(pot["return_levels"], key=float)]
    assert all(b > a for a, b in zip(levels, levels[1:]))
    assert pot["n_peaks"] >= 25
    assert pot["threshold_mm"] > 0


def test_peaks_over_threshold_declines_to_fit_without_exceedances():
    """A series with no variation has no peaks; return None rather than crash."""
    from src.a_rainfall.fit import peaks_over_threshold

    frame = synthetic_frame()
    assert peaks_over_threshold(frame["rain_mm"], ("06-01", "09-30")) is None
