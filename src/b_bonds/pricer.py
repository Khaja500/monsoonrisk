"""Module B pricing: burn analysis, quadrature and Monte Carlo.

Three methods are run on every bond so they can check each other (spec B.6):

  burn      - apply the payoff to each historical season, average
  analytic  - integrate the loss function against the fitted density
  mc        - sample the fitted distribution with antithetic variates

A cat bond's market convention is to price at par and quote a spread, so the
primary output is the fair spread under each risk rule; the price of a bond
carrying some other spread is reported alongside.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import integrate

from ..common.discounting import annual_factors
from .contracts import FACE, ParametricBond, WeatherCouponBond
from .premium import PremiumRule


@dataclass
class PricingResult:
    bond: dict
    rule: dict
    method: str
    fair_spread: float
    price_at_fair_spread: float
    expected_loss_annual: float
    expected_loss_total: float
    sd_loss_annual: float
    prob_attach: float
    prob_exhaust: float
    var95: float
    var99: float
    cvar95: float
    cvar99: float
    exceedance: list[dict] = field(default_factory=list)
    standard_error: float | None = None
    extras: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["bond"], d["rule"] = self.bond, self.rule
        return d


def _paths_from_sample(sample: np.ndarray, tenor: int, n_paths: int, seed: int) -> np.ndarray:
    """Burn analysis for a multi-year bond: resample observed seasons i.i.d.

    For a one-year bond this is just the historical record itself, which keeps
    the baseline method free of any distributional assumption.
    """
    if tenor == 1:
        return sample.reshape(-1, 1)
    rng = np.random.default_rng(seed)
    return rng.choice(sample, size=(n_paths, tenor), replace=True)


def _antithetic_draws(dist, tenor: int, n_paths: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    half = n_paths // 2
    u = rng.random((half, tenor))
    u = np.vstack([u, 1.0 - u])
    return dist.ppf(u)


def _investor_pv_loss(bond: ParametricBond, index_paths: np.ndarray, rate: float,
                      spread: float, collateral_yield: float) -> np.ndarray:
    """Present-value shortfall versus a loss-free bond, per path."""
    df = annual_factors(rate, bond.tenor)
    coupons, surviving = bond.cashflows(index_paths, collateral_yield, spread)
    pv = coupons @ df + surviving * df[-1]
    clean_coupons = (collateral_yield + spread) * FACE
    pv_clean = clean_coupons * df.sum() + FACE * df[-1]
    return pv_clean - pv


def price_parametric(bond: ParametricBond, distribution, rule: PremiumRule, rate: float,
                     collateral_yield: float, method: str = "mc", n_paths: int = 100_000,
                     seed: int = 20261013, market_spread: float | None = None) -> PricingResult:
    if method == "burn":
        paths = _paths_from_sample(distribution.burn_sample(), bond.tenor, n_paths, seed)
    elif method == "mc":
        paths = _antithetic_draws(distribution.dist, bond.tenor, n_paths, seed)
    elif method == "analytic":
        paths = _antithetic_draws(distribution.dist, bond.tenor, max(n_paths, 200_000), seed)
    else:
        raise ValueError(method)

    outstanding, applied, surviving = bond.principal_path(paths)
    df = annual_factors(rate, bond.tenor)
    pv_loss = applied @ df
    weights = rule.path_weights(pv_loss)

    eq_out = weights @ outstanding
    eq_surv = float(weights @ surviving)
    denom = float(eq_out @ df)
    par_spread = (FACE - eq_surv * df[-1] - collateral_yield * denom) / denom if denom else 0.0

    loss_frac = applied.sum(axis=1) / FACE
    el_annual = float(applied.mean(axis=0).mean() / FACE)
    sd_annual = float(applied.std(axis=0, ddof=1).mean() / FACE)
    moment_spread = rule.spread_from_moments(el_annual, sd_annual)
    fair_spread = float(moment_spread if moment_spread is not None else par_spread)

    coupons, surv2 = bond.cashflows(paths, collateral_yield, fair_spread)
    price = float(weights @ (coupons @ df + surv2 * df[-1]))

    first_year = paths[:, 0]
    attach_hit = (first_year <= bond.attach) if bond.inverted else (first_year >= bond.attach)
    exhaust_hit = (first_year <= bond.exhaust) if bond.inverted else (first_year >= bond.exhaust)

    losses_sorted = np.sort(loss_frac * FACE)
    def _var(q):
        return float(np.quantile(losses_sorted, q))
    def _cvar(q):
        cut = _var(q)
        tail = losses_sorted[losses_sorted >= cut]
        return float(tail.mean()) if len(tail) else cut

    grid = np.linspace(0, FACE * bond.tenor if bond.tenor > 1 else FACE, 51)
    exceedance = [{"loss": float(x), "prob": float((loss_frac * FACE > x).mean())} for x in grid]

    se = None
    if method in ("mc", "analytic"):
        se = float(np.std(applied.sum(axis=1), ddof=1) / np.sqrt(len(paths)) / FACE)

    extras = {"n_paths": int(len(paths)), "par_spread_under_Q": float(par_spread),
              "mean_index_year1": float(first_year.mean())}
    if method == "analytic" and bond.tenor >= 1:
        extras["quadrature_expected_loss_fraction"] = quadrature_expected_loss(bond, distribution)

    return PricingResult(bond.to_dict(), rule.to_dict(), method, fair_spread, price,
                         el_annual, float(loss_frac.mean()), sd_annual,
                         float(attach_hit.mean()), float(exhaust_hit.mean()),
                         _var(0.95), _var(0.99), _cvar(0.95), _cvar(0.99),
                         exceedance, se, extras)


def quadrature_expected_loss(bond: ParametricBond, distribution) -> float:
    """E[l] by numerical integration of the loss function against the fitted
    density - the independent check on the Monte Carlo mean (spec B.9)."""
    dist = distribution.dist
    lo, hi = dist.ppf(1e-8), dist.ppf(1 - 1e-8)
    f = lambda x: bond.loss_fraction(np.array([x]))[0] * dist.pdf(x)
    val, _err = integrate.quad(f, lo, hi, limit=400)
    return float(val)


def price_with_parameter_uncertainty(bond: ParametricBond, distribution, rule: PremiumRule,
                                     rate: float, collateral_yield: float, n_boot: int = 200,
                                     n_paths: int = 20_000, seed: int = 20261013) -> dict:
    """Bootstrap the seasons, refit, re-price - the band the 45-year record supports.

    The headline loss-exceedance curve is drawn from one distribution fitted to
    45 observations, with an exhaustion point near the 99th percentile.  Drawn
    alone it looks far more precise than the data warrants.  This resamples the
    observed seasons with replacement, refits the same family, and re-prices, so
    every published curve can carry the spread of curves the record is actually
    consistent with.
    """
    from ..a_rainfall.fit import SeasonDistribution
    from ..common.stats import select_distribution

    sample = np.asarray(distribution.burn_sample(), dtype=float)
    best = getattr(distribution, "best", None)
    family = best.family if best is not None else distribution.dist.dist.name
    rng = np.random.default_rng(seed)

    base = price_parametric(bond, distribution, rule, rate, collateral_yield, "mc", n_paths, seed)
    grid = np.array([row["loss"] for row in base.exceedance], dtype=float)
    curves, els, spreads, attach, exhaust = [], [], [], [], []

    for b in range(n_boot):
        draw = rng.choice(sample, size=len(sample), replace=True)
        try:
            best, _all = select_distribution(draw, [family])
            boot_dist = SeasonDistribution(bond.city, bond.trigger, draw, best, [best])
            res = price_parametric(bond, boot_dist, rule, rate, collateral_yield, "mc",
                                   n_paths, seed + 1 + b)
        except Exception:      # a resample the family will not fit is simply skipped
            continue
        curves.append([row["prob"] for row in res.exceedance])
        els.append(res.expected_loss_annual)
        spreads.append(res.fair_spread)
        attach.append(res.prob_attach)
        exhaust.append(res.prob_exhaust)

    if not curves:
        return {"n_boot": 0, "note": "no bootstrap resample could be fitted"}
    arr = np.array(curves)

    def band(values):
        v = np.asarray(values, dtype=float)
        return {"p05": float(np.quantile(v, 0.05)), "p50": float(np.quantile(v, 0.50)),
                "p95": float(np.quantile(v, 0.95))}

    return {
        "n_boot": int(len(curves)), "n_seasons": int(len(sample)), "family": family,
        "exceedance_band": [
            {"loss": float(x), "lo": float(np.quantile(arr[:, i], 0.05)),
             "mid": float(np.quantile(arr[:, i], 0.50)),
             "hi": float(np.quantile(arr[:, i], 0.95))}
            for i, x in enumerate(grid)],
        "expected_loss_annual": band(els),
        "fair_spread": band(spreads),
        "prob_attach": band(attach),
        "prob_exhaust": band(exhaust),
        "point_estimate": {"expected_loss_annual": base.expected_loss_annual,
                           "fair_spread": base.fair_spread,
                           "prob_attach": base.prob_attach,
                           "prob_exhaust": base.prob_exhaust},
    }


def price_coupon_bond(bond: WeatherCouponBond, distribution, rate: float,
                      method: str = "mc", n_paths: int = 100_000,
                      seed: int = 20261013) -> dict:
    if method == "burn":
        paths = _paths_from_sample(distribution.burn_sample(), bond.tenor, n_paths, seed)
    else:
        paths = _antithetic_draws(distribution.dist, bond.tenor, n_paths, seed)
    coupons, redemption = bond.cashflows(paths)
    df = annual_factors(rate, bond.tenor)
    pv = coupons @ df + redemption * df[-1]
    rates = bond.coupon_rate(paths)
    return {
        "bond": bond.to_dict(), "method": method, "n_paths": int(len(paths)),
        "price": float(pv.mean()),
        "price_se": float(pv.std(ddof=1) / np.sqrt(len(pv))),
        "mean_coupon_rate": float(rates.mean()),
        "coupon_rate_p05": float(np.quantile(rates, 0.05)),
        "coupon_rate_p95": float(np.quantile(rates, 0.95)),
        "prob_above_fixed": float((rates > bond.c_fixed + 1e-12).mean()),
        "price_quantiles": {str(q): float(np.quantile(pv, q)) for q in (0.05, 0.5, 0.95)},
    }
