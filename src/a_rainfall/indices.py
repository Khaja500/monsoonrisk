"""Module A, step 2: daily normals (LPA), season windows and season indices.

The RAINMUMBAI spot is an anchored cumulative deviation:

    spot_T = anchor + sum_{d in season, d <= T} (rain_d - LPA_d)

with anchor = 2,206.7 mm, the 1991-2020 Colaba/Santacruz seasonal normal.  At
the end of the season the anchor cancels the summed normal, so the September
settlement value is (to rounding) the realised seasonal rainfall in mm.  The
same construction is used for the two constructed city analogues.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..common.paths import load_config

SEASON_KEYS = ["CDR", "SEAS_TOTAL", "MAX1", "MAX3", "WET_DAYS"]


def daily_lpa(daily: pd.Series, start_year: int, end_year: int, window: int) -> pd.Series:
    """Smoothed mean rainfall for each calendar day over the baseline period.

    Indexed by 'MM-DD'.  Raw daily means are noisy, so a centred moving average
    is applied circularly across the calendar (window length is a config knob).
    """
    base = daily[(daily.index.year >= start_year) & (daily.index.year <= end_year)]
    key = base.index.strftime("%m-%d")
    raw = base.groupby(key).mean()
    calendar = pd.date_range("2020-01-01", "2020-12-31").strftime("%m-%d")
    raw = raw.reindex(calendar).interpolate().bfill().ffill()
    padded = pd.concat([raw.iloc[-window:], raw, raw.iloc[:window]])
    smooth = padded.rolling(window, center=True, min_periods=1).mean()
    return smooth.iloc[window:window + len(raw)]


def season_mask(index: pd.DatetimeIndex, start_md: str, end_md: str) -> np.ndarray:
    md = index.strftime("%m-%d").to_numpy()
    if start_md <= end_md:
        return (md >= start_md) & (md <= end_md)
    return (md >= start_md) | (md <= end_md)


def season_months(start_md: str, end_md: str) -> int:
    s, e = int(start_md[:2]), int(end_md[:2])
    return e - s + 1 if e >= s else (12 - s + 1) + e


def choose_season_window(daily: pd.Series, candidates: list[list[str]], start_year: int,
                         end_year: int, min_share: float = 0.75) -> tuple[list[str], list[dict]]:
    """Pick Bengaluru's season from data: the fewest months that still capture
    at least `min_share` of annual rainfall (ties broken on share)."""
    base = daily[(daily.index.year >= start_year) & (daily.index.year <= end_year)]
    annual = base.groupby(base.index.year).sum().mean()
    table = []
    for start_md, end_md in candidates:
        mask = season_mask(base.index, start_md, end_md)
        share = float(base[mask].groupby(base.index[mask].year).sum().mean() / annual)
        table.append({"window": [start_md, end_md], "months": season_months(start_md, end_md),
                      "share_of_annual": share})
    eligible = [t for t in table if t["share_of_annual"] >= min_share] or table
    best = sorted(eligible, key=lambda t: (t["months"], -t["share_of_annual"]))[0]
    return best["window"], table


def season_day_labels(window: tuple[str, str]) -> pd.Index:
    cal = pd.date_range("2021-01-01", "2021-12-31")
    return cal.strftime("%m-%d")[season_mask(pd.DatetimeIndex(cal), *window)]


def source_bias_factors(daily_frame: pd.DataFrame, window: tuple[str, str],
                        station_normal: float | None, start_year: int, end_year: int,
                        power_reference: pd.Series | None) -> dict[str, dict]:
    """One multiplicative bias factor per data source, onto the settlement basis.

    A 0.25-degree grid cell is not the station a contract settles on, and a
    reanalysis product is not the grid either.  Each source is therefore scaled
    so that its own 1991-2020 seasonal normal equals the published station
    normal.  Where no station normal is published (Bengaluru) every factor is
    1.0 and the grid is priced as-is.
    """
    labels = season_day_labels(window)
    out: dict[str, dict] = {}

    grid = daily_frame.loc[daily_frame["source_group"] == "imd_grid", "rain_mm"].astype(float)
    grid_lpa = float(daily_lpa(grid, start_year, end_year, 1).reindex(labels).sum())
    out["imd_grid"] = {"season_normal_mm": grid_lpa,
                       "factor": float(station_normal / grid_lpa) if station_normal else 1.0}
    # Real-time grids only start in the mid-2010s, too short for a 30-year
    # normal, so they inherit the archive grid's factor.
    out["imd_rt"] = dict(out["imd_grid"])

    if power_reference is not None and len(power_reference):
        p_lpa = float(daily_lpa(power_reference.astype(float), start_year, end_year, 1)
                      .reindex(labels).sum())
        out["nasa_power"] = {"season_normal_mm": p_lpa,
                             "factor": float(station_normal / p_lpa) if station_normal
                             else float(grid_lpa / p_lpa)}
    return out


@dataclass
class CityIndex:
    key: str
    label: str
    window: tuple[str, str]
    anchor_mm: float
    grid_lpa_mm: float
    bias: dict[str, dict]
    lpa: pd.Series                 # bias-corrected daily normal, 'MM-DD' indexed
    table: pd.DataFrame            # one row per season year
    daily: pd.Series               # bias-corrected daily rainfall
    provisional_from: pd.Timestamp | None
    window_table: list[dict] | None = None

    def cdr_path(self, year: int) -> pd.DataFrame:
        """Anchored CDR spot path through one season (what NCDEX publishes daily)."""
        mask = season_mask(self.daily.index, *self.window) & (self.daily.index.year == year)
        season = self.daily[mask]
        normal = self.lpa.reindex(season.index.strftime("%m-%d")).to_numpy()
        dev = season.to_numpy() - normal
        return pd.DataFrame({
            "date": season.index,
            "rain_mm": season.to_numpy(),
            "lpa_mm": normal,
            "deviation_mm": dev,
            "spot_mm": self.anchor_mm + np.cumsum(dev),
        })


def build_city_index(city_key: str, daily_frame: pd.DataFrame,
                     power_reference: pd.Series | None = None) -> CityIndex:
    cfg = load_config("cities")
    city = cfg["cities"][city_key]
    base = cfg["baseline"]
    daily = daily_frame["rain_mm"].astype(float)
    prov = daily_frame.index[daily_frame["is_provisional"].astype(bool)]
    provisional_from = prov.min() if len(prov) else None

    window_table = None
    if city["season"]:
        window = tuple(str(x) for x in city["season"])
    else:
        chosen, window_table = choose_season_window(
            daily, city["season_candidates"], base["lpa_start_year"], base["lpa_end_year"])
        window = tuple(chosen)

    season_md = season_day_labels(window)
    station_normal = city.get("station_normal_mm")
    bias = source_bias_factors(daily_frame, window, station_normal,
                               base["lpa_start_year"], base["lpa_end_year"], power_reference)

    # Every source is put on the settlement basis before any index is computed.
    factors = daily_frame["source_group"].map({k: v["factor"] for k, v in bias.items()}).astype(float)
    daily = daily * factors.to_numpy()

    archive = daily[daily_frame["source_group"].to_numpy() == "imd_grid"]
    lpa = daily_lpa(archive, base["lpa_start_year"], base["lpa_end_year"], base["smoothing_window"])
    grid_lpa = bias["imd_grid"]["season_normal_mm"]
    # With no published station normal the anchor is the city's own unsmoothed
    # 1991-2020 seasonal normal on the grid cell, so that mean CDR is zero.
    anchor = city["contract"]["anchor_mm"] or round(
        bias["imd_grid"]["season_normal_mm"] * bias["imd_grid"]["factor"], 1)

    # Smoothing moves a few mm across the season boundary, so the daily normal is
    # rescaled over the season days to sum exactly to the contract anchor.  That
    # is what makes the exchange's identity hold: spot at the end of the season
    # equals the realised seasonal rainfall.
    season_sum = float(lpa.reindex(season_md).sum())
    if season_sum > 0:
        lpa.loc[season_md] = lpa.reindex(season_md) * (anchor / season_sum)

    rows = []
    thresh = base["wet_day_threshold_mm"]
    season = daily[season_mask(daily.index, *window)]
    for year, chunk in season.groupby(season.index.year):
        if year < base["history_start_year"]:
            continue
        normal = lpa.reindex(chunk.index.strftime("%m-%d")).to_numpy()
        expected_days = len(pd.date_range(f"{year}-{window[0]}", f"{year}-{window[1]}"))
        rows.append({
            "year": int(year),
            "CDR": float(np.sum(chunk.to_numpy() - normal)),
            "SEAS_TOTAL": float(chunk.sum()),
            "MAX1": float(chunk.max()),
            "MAX3": float(chunk.rolling(3, min_periods=1).sum().max()),
            "WET_DAYS": int((chunk > thresh).sum()),
            "days_observed": int(len(chunk)),
            "days_expected": expected_days,
            "complete": bool(len(chunk) >= expected_days - 1),
            "provisional": bool(provisional_from is not None and year >= provisional_from.year),
        })
    table = pd.DataFrame(rows).set_index("year", drop=False)
    return CityIndex(city_key, city["label"], window, float(anchor), grid_lpa, bias,
                     lpa, table, daily, provisional_from, window_table)
