"""Module A, step 3: fit and select a distribution per city and index.

Totals and CDR get symmetric/skewed candidates; the 1-day and 3-day maxima get
a GEV, which is the natural family for block maxima.  Selection is by AIC, with
a Kolmogorov-Smirnov statistic and a percentile bootstrap of the empirical
quantiles reported alongside so the reader can see how thin the evidence is in
the tail - roughly 45 season observations per city.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

from ..common.stats import (FitResult, bootstrap_quantiles, lag1_autocorr,
                            select_distribution, theil_sen_trend)

FAMILIES = {
    "CDR": ["norm", "skewnorm", "gamma", "logistic"],
    "SEAS_TOTAL": ["gamma", "norm", "skewnorm", "lognorm"],
    "MAX1": ["genextreme", "gamma", "lognorm"],
    "MAX3": ["genextreme", "gamma", "lognorm"],
    "WET_DAYS": ["norm", "skewnorm"],
}
QUANTILES = [0.02, 0.05, 0.10, 0.20, 0.50, 0.80, 0.90, 0.95, 0.98]
POT_QUANTILES = [0.90, 0.95, 0.98, 0.99]


def peaks_over_threshold(daily: pd.Series, window: tuple[str, str], threshold_q: float = 0.95,
                         run_days: int = 3, horizon_days: int = 3) -> dict | None:
    """Generalised Pareto fit to independent exceedances of a high threshold.

    An annual-maxima GEV throws away every large event in a season except the
    largest, which is a costly thing to do with 45 seasons.  Peaks over
    threshold uses them all: it declusters the season's rolling `horizon_days`
    rainfall into independent peaks at least `run_days` apart, fits a GPD to
    the exceedances, and converts the result back to return levels for the
    annual maximum via the exceedance rate.  Reported as a cross-check on the
    GEV tail, not as a replacement for it.
    """
    from .indices import season_mask

    season = daily[season_mask(daily.index, *window)]
    if len(season) < 500:
        return None
    rolled = season.rolling(horizon_days, min_periods=1).sum()
    threshold = float(np.quantile(rolled.to_numpy(), threshold_q))

    # decluster: keep local maxima separated by at least run_days
    values, dates = rolled.to_numpy(), rolled.index
    peaks, i = [], 0
    while i < len(values):
        if values[i] <= threshold:
            i += 1
            continue
        j = i
        while j + 1 < len(values) and (dates[j + 1] - dates[j]).days <= run_days:
            j += 1
        peaks.append(float(values[i:j + 1].max()))
        i = j + 1
    excess = np.array([p - threshold for p in peaks])
    if len(excess) < 25:
        return None

    shape, loc, scale = stats.genpareto.fit(excess, floc=0.0)
    n_seasons = len(set(season.index.year))
    rate = len(excess) / n_seasons                       # peaks per season
    levels = {}
    for q in POT_QUANTILES:
        # P(annual max <= x) = q  <=>  rate * P(excess > x - u) = -ln(q)
        p_exceed = -np.log(q) / rate
        if not 0 < p_exceed < 1:
            continue
        levels[str(q)] = float(threshold + stats.genpareto.ppf(1 - p_exceed, shape, loc=0.0,
                                                              scale=scale))
    return {
        "threshold_mm": threshold, "threshold_quantile": threshold_q,
        "n_peaks": int(len(excess)), "peaks_per_season": float(rate),
        "shape_xi": float(shape), "scale_beta": float(scale),
        "return_levels": levels,
        "note": ("GPD on declustered peaks of the %d-day rolling total; return levels are "
                 "for the seasonal maximum" % horizon_days),
    }


@dataclass
class SeasonDistribution:
    city: str
    index: str
    sample: np.ndarray
    best: FitResult
    all_fits: list[FitResult]

    @property
    def dist(self):
        return self.best.frozen()

    def cdf(self, x):
        return self.dist.cdf(x)

    def sf(self, x):
        return self.dist.sf(x)

    def ppf(self, q):
        return self.dist.ppf(q)

    def sample_draws(self, n: int, seed: int = 0) -> np.ndarray:
        rng = np.random.default_rng(seed)
        return np.asarray(self.dist.rvs(size=n, random_state=rng), dtype=float)

    def burn_sample(self) -> np.ndarray:
        return self.sample

    def to_dict(self) -> dict:
        return {
            "city": self.city,
            "index": self.index,
            "n": int(len(self.sample)),
            "mean": float(np.mean(self.sample)),
            "sd": float(np.std(self.sample, ddof=1)),
            "skew": float(stats.skew(self.sample)),
            "min": float(np.min(self.sample)),
            "max": float(np.max(self.sample)),
            "lag1_autocorr": lag1_autocorr(self.sample),
            "best": self.best.to_dict(),
            "candidates": [f.to_dict() for f in self.all_fits],
            "empirical_quantiles": bootstrap_quantiles(self.sample, QUANTILES, seed=7),
            "fitted_quantiles": {str(q): float(self.ppf(q)) for q in QUANTILES},
            "sample_values": [float(v) for v in self.sample],
        }


def fit_city(city_key: str, table: pd.DataFrame, indices: list[str] | None = None,
             complete_only: bool = True) -> dict[str, SeasonDistribution]:
    """Fit on complete, non-provisional seasons only: the current season is
    incomplete and its data has not been quality-controlled by IMD yet."""
    rows = table[table["complete"] & ~table["provisional"]] if complete_only else table
    out = {}
    for index in (indices or list(FAMILIES)):
        sample = rows[index].to_numpy(dtype=float)
        best, fits = select_distribution(sample, FAMILIES[index])
        out[index] = SeasonDistribution(city_key, index, sample, best, fits)
    return out


def trend_report(table: pd.DataFrame, index: str = "SEAS_TOTAL") -> dict:
    rows = table[table["complete"]]
    return theil_sen_trend(rows["year"].to_numpy(dtype=float), rows[index].to_numpy(dtype=float))


def cross_city_correlation(tables: dict[str, pd.DataFrame], index: str = "SEAS_TOTAL") -> dict:
    """Spearman rank correlation of annual indices - needed before any
    multi-city basket bond is priced."""
    frames = {k: v[v["complete"]].set_index("year")[index] for k, v in tables.items()}
    joined = pd.DataFrame(frames).dropna()
    keys = list(joined.columns)
    out = {"years": [int(y) for y in joined.index], "pairs": {}}
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            rho = stats.spearmanr(joined[a], joined[b])
            out["pairs"][f"{a}~{b}"] = {"spearman": float(rho.statistic),
                                        "pvalue": float(rho.pvalue)}
    return out
