"""Module C, method M2: Longstaff-Schwartz Monte Carlo for the game option.

The regression recursion is the American one with the issuer's right added at
each decision date:

    candidate = max(G_i, C_hat_i)
    value     = H_i                     if candidate > H_i      (issuer cancels)
                G_i                     elif G_i >= C_hat_i     (holder exercises)
                discounted continuation otherwise

arXiv 2401.08093 proposes a two-step variant for this problem; that paper has
not been read here, so the baseline recursion above is what is implemented and
the tree is used as the cross-check (spec C.5 allows exactly this).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .binomial import payoff


def simulate_gbm(s0: float, r: float, q: float, sigma: float, maturity: float, steps: int,
                 n_paths: int, seed: int, antithetic: bool = True) -> np.ndarray:
    """Exact GBM paths, shape (n_paths, steps + 1)."""
    rng = np.random.default_rng(seed)
    dt = maturity / steps
    half = n_paths // 2 if antithetic else n_paths
    z = rng.standard_normal((half, steps))
    if antithetic:
        z = np.vstack([z, -z])
    drift = (r - q - 0.5 * sigma ** 2) * dt
    increments = drift + sigma * np.sqrt(dt) * z
    log_paths = np.concatenate([np.zeros((z.shape[0], 1)), np.cumsum(increments, axis=1)], axis=1)
    return s0 * np.exp(log_paths)


def black_scholes(spot: np.ndarray, strike: float, r: float, q: float, sigma: float,
                  tau: float, kind: str) -> np.ndarray:
    """European value - used as a regression basis function, not as a price."""
    spot = np.asarray(spot, dtype=float)
    if tau <= 0:
        return payoff(spot, strike, kind)
    from scipy.stats import norm
    sd = sigma * np.sqrt(tau)
    d1 = (np.log(np.maximum(spot, 1e-12) / strike) + (r - q + 0.5 * sigma ** 2) * tau) / sd
    d2 = d1 - sd
    if kind == "put":
        return strike * np.exp(-r * tau) * norm.cdf(-d2) - spot * np.exp(-q * tau) * norm.cdf(-d1)
    return spot * np.exp(-q * tau) * norm.cdf(d1) - strike * np.exp(-r * tau) * norm.cdf(d2)


def _basis(x: np.ndarray, degree: int, scale: float, extra: np.ndarray | None = None) -> np.ndarray:
    """Polynomials in S/K, the two intrinsic kinks, and optionally the European
    value with the remaining maturity.

    Two things drive this choice.  The issuer's cancellation decision needs a
    continuation estimate at *every* path, not only the in-the-money ones, so
    the regression is fitted on all paths.  And the decision compares a level
    against G + delta, so the fit has to be accurate near the strike, where the
    time value peaks: a plain low-degree polynomial is not, and the European
    value is - it carries almost the whole shape, leaving the polynomial to fit
    only the early-exercise and cancellation corrections.
    """
    xs = x / scale
    cols = [xs ** k for k in range(degree + 1)]
    cols.append(np.maximum(1.0 - xs, 0.0))
    cols.append(np.maximum(xs - 1.0, 0.0))
    if extra is not None:
        cols.append(np.asarray(extra, dtype=float) / scale)
    return np.column_stack(cols)


@dataclass
class LSMResult:
    price: float
    stderr: float
    n_paths: int
    steps: int
    ci: tuple[float, float]
    exercise_rate: float
    cancel_rate: float

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["ci"] = [float(self.ci[0]), float(self.ci[1])]
        return d


def price_lsm(s0: float, strike: float, r: float, q: float, sigma: float, maturity: float,
              kind: str = "put", penalty: float = 0.0, n_paths: int = 100_000,
              steps: int = 100, degree: int = 4, seed: int = 20261013,
              paths: np.ndarray | None = None) -> LSMResult:
    if paths is None:
        paths = simulate_gbm(s0, r, q, sigma, maturity, steps, n_paths, seed)
    n_paths, n_cols = paths.shape
    steps = n_cols - 1
    dt = maturity / steps
    disc = float(np.exp(-r * dt))

    value = payoff(paths[:, -1], strike, kind)
    exercised = np.zeros(n_paths, dtype=bool)
    cancelled = np.zeros(n_paths, dtype=bool)

    for i in range(steps - 1, 0, -1):
        spot = paths[:, i]
        g = payoff(spot, strike, kind)
        cont = disc * value
        itm = g > 0
        tau = maturity - i * dt
        euro = black_scholes(spot, strike, r, q, sigma, tau, kind)
        design = _basis(spot, degree, strike, euro)
        coeff, *_ = np.linalg.lstsq(design, cont, rcond=None)
        chat = np.maximum(design @ coeff, 0.0)
        h = g + penalty
        candidate = np.maximum(g, chat)
        cancel = candidate > h + 1e-12
        exercise = (~cancel) & (g >= chat) & itm
        value = np.where(cancel, h, np.where(exercise, g, cont))
        cancelled |= cancel
        exercised |= exercise

    value = disc * value
    g0 = payoff(np.array([s0]), strike, kind)[0]
    price0 = float(min(g0 + penalty, max(g0, value.mean())))
    se = float(value.std(ddof=1) / np.sqrt(n_paths))
    return LSMResult(price0, se, int(n_paths), int(steps),
                     (price0 - 1.96 * se, price0 + 1.96 * se),
                     float(exercised.mean()), float(cancelled.mean()))
