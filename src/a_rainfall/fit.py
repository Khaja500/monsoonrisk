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
