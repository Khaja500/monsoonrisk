"""The rainfall index future - RAINMUMBAI and the two constructed analogues.

NCDEX publishes a daily anchored cumulative-deviation spot,

    spot_T = anchor + sum_{d <= T} (rain_d - LPA_d),

and the contract for month M settles on that spot just after month end.  At the
end of the season the summed normal cancels the anchor, so the September
settlement value equals the realised seasonal rainfall in mm.

Fair value at a valuation date is the spot plus the expected remaining
deviation:

    F = spot(t) + (factor - 1) * LPA(t, T] + lambda * sd(t, T]

`factor` is a seasonal forecast as a fraction of the LPA and `lambda` is a
market price of risk, zero by default.  Note what the first term implies: with
a climatological forecast (factor = 1, no risk premium) fair value equals the
current spot, so the future is a martingale under climatology and every
departure from spot has to be argued for explicitly.

Where the factor comes from is the whole question.  IMD's published outlook is
categorical and its category centre is 1.00, which makes the term vanish, so
`src/b_bonds/forecast.py` fits a seasonal forecast on climate state known
before the season opens and scores it out of sample against climatology.  Its
selected variant - which for two of the three cities is climatology itself -
supplies the factor here.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..a_rainfall.indices import CityIndex, season_mask


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
    forecast_label: str = "climatology"

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
        forecast_component = (self.forecast_factor - 1.0) * lpa_rem
        premium = self.risk_lambda * sd_rem
        fv = spot + forecast_component + premium
        return {
            "asof": asof.strftime("%Y-%m-%d"),
            "expiry": expiry.strftime("%Y-%m-%d"),
            "spot_mm": spot,
            "remaining_normal_mm": lpa_rem,
            "remaining_sd_mm": sd_rem,
            "forecast_factor": float(self.forecast_factor),
            "forecast_label": self.forecast_label,
            "forecast_component_mm": float(forecast_component),
            "risk_premium_mm": float(premium),
            "fair_value_mm": float(fv),
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
             walk_forward_rows: list[dict] | None = None) -> dict:
    """Season-start fair value against realised settlement, year by year.

    Two models are scored on the same seasons: climatology, which quotes the
    anchor, and the statistical forecast, whose variant and coefficients are
    both chosen on seasons strictly before the one being priced (see
    `forecast.walk_forward`).  The 1991-2020 normal is a fixed contract
    parameter and is deliberately not re-estimated.
    """
    wf = {row["year"]: row for row in (walk_forward_rows or [])}
    rows = []
    for year in range(start_year, end_year + 1):
        if year not in ci.table.index:
            continue
        rec = ci.table.loc[year]
        season_start = _season_dates(year, ci.window)[0]
        exp = _season_dates(year, ci.window)[-1]
        asof = season_start - pd.Timedelta(days=1)

        factor = wf.get(year, {}).get("factor", 1.0)
        forecast_model = FuturesModel(ci, forecast_factor=factor,
                                   forecast_label=wf.get(year, {}).get("variant", "climatology"))
        naive_model = FuturesModel(ci, forecast_factor=1.0)
        fv_forecast = forecast_model.fair_value(year, asof, exp)["fair_value_mm"]
        fv_naive = naive_model.fair_value(year, asof, exp)["fair_value_mm"]
        settled = ci.anchor_mm + float(rec["CDR"])
        rows.append({
            "year": int(year),
            "settlement_mm": settled,
            "season_total_mm": float(rec["SEAS_TOTAL"]),
            "fair_value_forecast_mm": float(fv_forecast),
            "forecast_variant": wf.get(year, {}).get("variant", "climatology"),
            "forecast_factor": float(factor),
            "fair_value_anchor_mm": float(fv_naive),
            "error_forecast_mm": float(fv_forecast - settled),
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
        "forecast_model": stats("error_forecast_mm"),
        "anchor_model": stats("error_anchor_mm"),
        "forecast_beats_anchor_pct": float(100.0 * np.mean(
            np.abs(done["error_forecast_mm"]) < np.abs(done["error_anchor_mm"]))) if len(done) else 0.0,
        "models_identical_pct": float(100.0 * np.mean(
            np.isclose(done["error_forecast_mm"], done["error_anchor_mm"]))) if len(done) else 0.0,
        "mean_abs_pnl_inr_per_lot": float(np.abs(done["pnl_long_at_anchor_inr"]).mean()) if len(done) else 0.0,
    }
