"""Shared statistics helpers: distribution selection, bootstrap intervals."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import stats


@dataclass
class FitResult:
    family: str
    params: tuple
    aic: float
    ks_stat: float
    ks_pvalue: float
    loglik: float

    def frozen(self):
        return getattr(stats, self.family)(*self.params)

    def to_dict(self) -> dict:
        return {
            "family": self.family,
            "params": [float(p) for p in self.params],
            "aic": float(self.aic),
            "ks_stat": float(self.ks_stat),
            "ks_pvalue": float(self.ks_pvalue),
            "loglik": float(self.loglik),
        }


def fit_family(sample: np.ndarray, family: str, **kwargs) -> FitResult:
    dist = getattr(stats, family)
    params = dist.fit(sample, **kwargs)
    loglik = float(np.sum(dist.logpdf(sample, *params)))
    aic = 2 * len(params) - 2 * loglik
    ks = stats.kstest(sample, family, args=params)
    return FitResult(family, tuple(float(p) for p in params), aic, float(ks.statistic),
                     float(ks.pvalue), loglik)


def select_distribution(sample: np.ndarray, families: list[str]) -> tuple[FitResult, list[FitResult]]:
    """Fit every candidate family by maximum likelihood and rank by AIC.

    Location-bounded families (gamma, lognorm) are fitted with floc=0 on
    strictly positive samples so the fit stays interpretable; on samples that
    can be negative (CDR) they are skipped by the caller.
    """
    fits: list[FitResult] = []
    for family in families:
        try:
            if family in ("gamma", "lognorm", "weibull_min") and sample.min() > 0:
                fits.append(fit_family(sample, family, floc=0))
            else:
                fits.append(fit_family(sample, family))
        except Exception:  # a family that will not converge is simply not a candidate
            continue
    if not fits:
        raise RuntimeError("no candidate distribution could be fitted")
    fits.sort(key=lambda f: f.aic)
    return fits[0], fits


def bootstrap_quantiles(sample: np.ndarray, quantiles: list[float], n_boot: int = 2000,
                        seed: int = 0) -> dict:
    """Percentile bootstrap intervals for empirical quantiles."""
    rng = np.random.default_rng(seed)
    n = len(sample)
    draws = rng.choice(sample, size=(n_boot, n), replace=True)
    out = {}
    for q in quantiles:
        qs = np.quantile(draws, q, axis=1)
        out[str(q)] = {
            "point": float(np.quantile(sample, q)),
            "lo": float(np.quantile(qs, 0.025)),
            "hi": float(np.quantile(qs, 0.975)),
        }
    return out


def lag1_autocorr(sample: np.ndarray) -> float:
    x = np.asarray(sample, dtype=float)
    if len(x) < 3:
        return float("nan")
    x = x - x.mean()
    return float(np.sum(x[1:] * x[:-1]) / np.sum(x * x))


def theil_sen_trend(years: np.ndarray, values: np.ndarray) -> dict:
    """Robust linear trend (mm per year) with a Mann-Kendall significance test."""
    res = stats.theilslopes(values, years, 0.95)
    mk = stats.kendalltau(years, values)
    return {
        "slope_mm_per_year": float(res[0]),
        "intercept": float(res[1]),
        "lo": float(res[2]),
        "hi": float(res[3]),
        "kendall_tau": float(mk.statistic),
        "kendall_p": float(mk.pvalue),
    }
