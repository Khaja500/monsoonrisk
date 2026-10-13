"""The rainfall index future - RAINMUMBAI and the two constructed analogues.

NCDEX publishes a daily anchored cumulative-deviation spot,

    spot_T = anchor + sum_{d <= T} (rain_d - LPA_d),

and the contract for month M settles on that spot just after month end.  At the
end of the season the summed normal cancels the anchor, so the September
settlement value equals the realised seasonal rainfall in mm.

Fair value at a valuation date is the spot plus the expected remaining
deviation:

    F = spot(t) + (factor - 1) * LPA(t, T] + trend(t, T] + lambda * sd(t, T]

`factor` is the published seasonal outlook as a fraction of the LPA (IMD's
category centre), `trend` is a Theil-Sen trend in seasonal totals extrapolated
to the current year, and `lambda` is a market price of risk, zero by default.
Note what the first term implies: with a climatological forecast (factor = 1,
no trend, no risk premium) fair value equals the current spot, so the future is
a martingale under climatology and every departure from spot has to be argued
for explicitly.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..a_rainfall.indices import CityIndex, season_mask
from ..common.stats import theil_sen_trend


def _season_dates(year: int, window: tuple[str, str]) -> pd.DatetimeIndex:
    return pd.date_range(f"{year}-{window[0]}", f"{year}-{window[1]}")


def spot_series(ci: CityIndex, year: int) -> pd.Series:
    """The anchored CDR spot through one season, as the exchange would publish it."""
    path = ci.cdr_path(year)
    return pd.Series(path["spot_mm"].to_numpy(), index=pd.DatetimeIndex(path["date"]))


def expiry_date(year: int, month: int) -> pd.Timestamp:
    """Final settlement date: the contract stops trading on the business day
    before the last working calendar day of the month and settles on the spot
    of the next calendar day, i.e. effectively on the month's last day."""
    return pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)


@dataclass
class FuturesModel:
    ci: CityIndex
    forecast_factor: float = 1.0
    risk_lambda: float = 0.0
    use_trend: bool = True
    trend_fit_through: int | None = None     # expanding-window backtests set this

    def _trend_slope(self) -> dict:
        rows = self.ci.table[self.ci.table["complete"]]
        if self.trend_fit_through is not None:
            rows = rows[rows["year"] <= self.trend_fit_through]
        if len(rows) < 10:
            return {"slope_mm_per_year": 0.0, "kendall_p": 1.0, "intercept": 0.0,
                    "lo": 0.0, "hi": 0.0, "kendall_tau": 0.0}
        return theil_sen_trend(rows["year"].to_numpy(float), rows["SEAS_TOTAL"].to_numpy(float))

    def remaining_normal(self, year: int, asof: pd.Timestamp, expiry: pd.Timestamp) -> float:
        dates = _season_dates(year, self.ci.window)
        sel = dates[(dates > asof) & (dates <= expiry)]
        return float(self.ci.lpa.reindex(sel.strftime("%m-%d")).sum())

    def remaining_sd(self, year: int, asof: pd.Timestamp, expiry: pd.Timestamp) -> float:
        """Standard deviation of the deviation still to accumulate, measured on
        the same calendar stretch in every historical season."""
        dates = _season_dates(year, self.ci.window)
        sel = dates[(dates > asof) & (dates <= expiry)]
        if len(sel) == 0:
            return 0.0
        labels = set(sel.strftime("%m-%d"))
        daily = self.ci.daily
        md = daily.index.strftime("%m-%d")
        chunk = daily[np.isin(md, list(labels))]
        normal = float(self.ci.lpa.reindex(sorted(labels)).sum())
        totals = chunk.groupby(chunk.index.year).sum()
        totals = totals[totals.index < year] if len(totals[totals.index < year]) > 5 else totals
        return float((totals - normal).std(ddof=1))

    def spot(self, year: int, asof: pd.Timestamp) -> float:
        s = spot_series(self.ci, year)
        s = s[s.index <= asof]
        return float(s.iloc[-1]) if len(s) else self.ci.anchor_mm

    def fair_value(self, year: int, asof: pd.Timestamp, expiry: pd.Timestamp) -> dict:
        spot = self.spot(year, asof)
        lpa_rem = self.remaining_normal(year, asof, expiry)
        sd_rem = self.remaining_sd(year, asof, expiry)
        trend = self._trend_slope()
        season_lpa = float(self.ci.lpa.reindex(
            _season_dates(year, self.ci.window).strftime("%m-%d")).sum())
        trend_component = 0.0
        if self.use_trend and trend["kendall_p"] < 0.10 and season_lpa > 0:
            mid = 2005.5                      # centre of the 1991-2020 baseline window
            trend_component = trend["slope_mm_per_year"] * (year - mid) * (lpa_rem / season_lpa)
        forecast_component = (self.forecast_factor - 1.0) * lpa_rem
        premium = self.risk_lambda * sd_rem
        fv = spot + forecast_component + trend_component + premium
        return {
            "asof": asof.strftime("%Y-%m-%d"),
            "expiry": expiry.strftime("%Y-%m-%d"),
            "spot_mm": spot,
            "remaining_normal_mm": lpa_rem,
            "remaining_sd_mm": sd_rem,
            "forecast_component_mm": float(forecast_component),
            "trend_component_mm": float(trend_component),
            "risk_premium_mm": float(premium),
            "fair_value_mm": float(fv),
            "trend_slope_mm_per_year": trend["slope_mm_per_year"],
            "trend_kendall_p": trend["kendall_p"],
        }

    def settlement(self, year: int, expiry: pd.Timestamp) -> float | None:
        s = spot_series(self.ci, year)
        s = s[s.index <= expiry]
        return float(s.iloc[-1]) if len(s) else None


def monthly_contracts(ci: CityIndex, year: int, months: list[int], model: FuturesModel,
                      asof: pd.Timestamp, value_at: str = "live") -> list[dict]:
    """Fair value and realised settlement for each listed contract month.

    `value_at="live"` marks every contract as of today, which is what a trader
    sees for a season still running.  `value_at="season_start"` marks all of
    them the day before the season opens, which is the only honest way to score
    the model against a settlement that has already happened.
    """
    out = []
    season = _season_dates(year, ci.window)
    for month in months:
        exp = expiry_date(year, month)
        if value_at == "season_start":
            mark = season[0] - pd.Timedelta(days=1)
        else:
            mark = min(asof, exp)
        row = model.fair_value(year, mark, exp)
        settled = model.settlement(year, exp)
        row.update({
            "month": int(month),
            "contract": f"{ci.key.upper()}-{exp.strftime('%b%y').upper()}",
            "settlement_mm": settled,
            "settled": bool(settled is not None and exp <= asof),
        })
        if row["settled"]:
            row["error_mm"] = float(row["fair_value_mm"] - settled)
            row["pnl_long_inr_per_lot"] = float((settled - row["fair_value_mm"]) * 50.0)
        out.append(row)
    return out


def backtest(ci: CityIndex, start_year: int, end_year: int, multiplier: float = 50.0,
             forecast_factor: float = 1.0) -> dict:
    """Season-start fair value against realised settlement, year by year.

    The trend is refitted each year on seasons strictly before it, so the trend
    model never sees its own target.  The 1991-2020 normal is a fixed contract
    parameter and is deliberately not re-estimated.
    """
    rows = []
    for year in range(start_year, end_year + 1):
        if year not in ci.table.index:
            continue
        rec = ci.table.loc[year]
        season_start = _season_dates(year, ci.window)[0]
        exp = _season_dates(year, ci.window)[-1]
        asof = season_start - pd.Timedelta(days=1)

        trend_model = FuturesModel(ci, forecast_factor=forecast_factor, use_trend=True,
                                   trend_fit_through=year - 1)
        naive_model = FuturesModel(ci, forecast_factor=1.0, use_trend=False)
        fv_trend = trend_model.fair_value(year, asof, exp)["fair_value_mm"]
        fv_naive = naive_model.fair_value(year, asof, exp)["fair_value_mm"]
        settled = ci.anchor_mm + float(rec["CDR"])
        rows.append({
            "year": int(year),
            "settlement_mm": settled,
            "season_total_mm": float(rec["SEAS_TOTAL"]),
            "fair_value_trend_mm": float(fv_trend),
            "fair_value_anchor_mm": float(fv_naive),
            "error_trend_mm": float(fv_trend - settled),
            "error_anchor_mm": float(fv_naive - settled),
            "pnl_long_at_anchor_inr": float((settled - fv_naive) * multiplier),
            "complete": bool(rec["complete"]),
            "provisional": bool(rec["provisional"]),
        })
    frame = pd.DataFrame(rows)
    done = frame[frame["complete"]]

    def stats(col):
        e = done[col].to_numpy(float)
        return {"bias_mm": float(e.mean()), "mae_mm": float(np.abs(e).mean()),
                "rmse_mm": float(np.sqrt((e ** 2).mean())),
                "worst_mm": float(e[np.abs(e).argmax()]) if len(e) else 0.0}

    return {
        "rows": rows,
        "n_years": int(len(done)),
        "trend_model": stats("error_trend_mm"),
        "anchor_model": stats("error_anchor_mm"),
        "trend_beats_anchor_pct": float(100.0 * np.mean(
            np.abs(done["error_trend_mm"]) < np.abs(done["error_anchor_mm"]))) if len(done) else 0.0,
        "models_identical_pct": float(100.0 * np.mean(
            np.isclose(done["error_trend_mm"], done["error_anchor_mm"]))) if len(done) else 0.0,
        "mean_abs_pnl_inr_per_lot": float(np.abs(done["pnl_long_at_anchor_inr"]).mean()) if len(done) else 0.0,
    }
