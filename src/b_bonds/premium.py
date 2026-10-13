"""Module B risk premium rules.

The rainfall index is not tradeable, so there is no hedge-based price and no
single correct measure.  Three rules are implemented and always reported side
by side; none of them is calibrated to a market, because India has no
catastrophe bond or rainfall bond market to calibrate against.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats


def wang_weights(n: int, lam: float) -> np.ndarray:
    """Probability weights for an ascending-sorted sample under the Wang transform.

    The transform distorts the survival function,
        S_Q(x) = Phi( Phi^-1( S_P(x) ) + lam ),
    so for a sample sorted ascending the Q-probability of observation i is the
    drop in the distorted survival function across that observation.  lam = 0
    returns the physical weights 1/n.
    """
    if n < 1:
        raise ValueError("empty sample")
    u = np.arange(n, -1, -1, dtype=float) / n          # survival at each step, 1 -> 0
    g = stats.norm.cdf(stats.norm.ppf(np.clip(u, 1e-12, 1 - 1e-12)) + lam)
    g[0], g[-1] = 1.0, 0.0
    w = g[:-1] - g[1:]
    return w / w.sum()


def distorted_expectation(sample: np.ndarray, lam: float) -> float:
    """E_Q[X] under the Wang transform, computed from a sample."""
    s = np.sort(np.asarray(sample, dtype=float))
    return float(np.dot(s, wang_weights(len(s), lam)))


def wang_weights_for(sample: np.ndarray, lam: float) -> np.ndarray:
    """Wang weights aligned to the ORIGINAL order of `sample`.

    Used to re-weight whole simulated paths (ranked by their total loss) so
    every quantity of a path - outstanding principal, coupons, redemption - is
    averaged under the same pricing measure.
    """
    order = np.argsort(np.asarray(sample, dtype=float), kind="stable")
    w_sorted = wang_weights(len(sample), lam)
    w = np.empty_like(w_sorted)
    w[order] = w_sorted
    return w


@dataclass
class PremiumRule:
    rule: str                 # "r1" | "wang" | "sd"
    m: float = 1.0            # R1 expected-loss multiple
    lam: float = 0.0          # R2 Wang lambda
    beta: float = 0.0         # R3 standard-deviation loading

    @classmethod
    def r1(cls, m: float) -> "PremiumRule":
        return cls("r1", m=m)

    @classmethod
    def wang(cls, lam: float) -> "PremiumRule":
        return cls("wang", lam=lam)

    @classmethod
    def sd_load(cls, beta: float) -> "PremiumRule":
        return cls("sd", beta=beta)

    @property
    def label(self) -> str:
        return {"r1": f"R1 expected-loss multiple m={self.m:g}",
                "wang": f"R2 Wang transform lambda={self.lam:g}",
                "sd": f"R3 SD loading beta={self.beta:g}"}[self.rule]

    def path_weights(self, path_loss: np.ndarray) -> np.ndarray:
        """Pricing-measure weights over simulated paths."""
        n = len(path_loss)
        if self.rule == "wang":
            return wang_weights_for(path_loss, self.lam)
        return np.full(n, 1.0 / n)

    def spread_from_moments(self, el_annual: float, sd_annual: float) -> float | None:
        """Closed-form fair spread for the two moment-based rules (as a decimal
        of face).  The Wang rule has no closed form here: its spread comes from
        the par condition under Q, solved in pricer.py."""
        if self.rule == "r1":
            return self.m * el_annual
        if self.rule == "sd":
            return el_annual + self.beta * sd_annual
        return None

    def to_dict(self) -> dict:
        return {"rule": self.rule, "label": self.label, "m": self.m, "lam": self.lam,
                "beta": self.beta}
