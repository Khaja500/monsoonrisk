"""Module B instruments: principal-at-risk bond, weather-linked coupon bond and
the CDR index future.

Face value is normalised to 100 throughout.  Everything here is pure payoff
arithmetic on an array of season index values - no pricing, no measure.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

FACE = 100.0


@dataclass
class ParametricBond:
    """B1: principal-at-risk parametric catastrophe bond.

    `inverted = False` is the flood case: loss grows as the index rises above
    attachment.  `inverted = True` is the drought case: attachment sits above
    exhaustion and loss grows as the index falls.
    """
    city: str
    trigger: str
    attach: float
    exhaust: float
    tenor: int
    inverted: bool = False
    aggregate: bool = False
    face: float = FACE

    def __post_init__(self):
        # A == E is allowed: it degenerates to a binary trigger, which spec B.9
        # uses as its first acceptance test.
        if self.inverted and self.attach < self.exhaust:
            raise ValueError("inverted trigger needs attach >= exhaust")
        if not self.inverted and self.exhaust < self.attach:
            raise ValueError("flood trigger needs exhaust >= attach")

    def loss_fraction(self, index_values: np.ndarray) -> np.ndarray:
        """Payout ratio in [0, 1] per season.  A = E degenerates to a binary
        trigger, which is the first acceptance test in spec B.9."""
        x = np.asarray(index_values, dtype=float)
        span = self.attach - self.exhaust if self.inverted else self.exhaust - self.attach
        if span == 0:
            return (x <= self.attach).astype(float) if self.inverted else (x >= self.attach).astype(float)
        raw = (self.attach - x) / span if self.inverted else (x - self.attach) / span
        return np.clip(raw, 0.0, 1.0)

    def principal_path(self, index_paths: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Principal at risk, principal actually written down, and the surviving
        principal at maturity, for index paths shaped (n_paths, tenor).

        Losses are capped at the principal still outstanding, so principal can
        never go negative (spec B.9).
        """
        idx = np.atleast_2d(np.asarray(index_paths, dtype=float))
        if self.aggregate:
            losses = np.zeros_like(idx)
            losses[:, -1] = self.loss_fraction(idx.sum(axis=1)) * self.face
        else:
            losses = self.loss_fraction(idx) * self.face
        outstanding = np.empty_like(losses)
        applied = np.empty_like(losses)
        remaining = np.full(idx.shape[0], self.face)
        for t in range(idx.shape[1]):
            outstanding[:, t] = remaining           # principal at risk through year t+1
            applied[:, t] = np.minimum(remaining, losses[:, t])
            remaining = remaining - applied[:, t]
        return outstanding, applied, remaining

    def cashflows(self, index_paths: np.ndarray, collateral_yield: float,
                  spread: float) -> tuple[np.ndarray, np.ndarray]:
        """Coupons per year and redemption at maturity, per path.

        The coupon accrues on the principal outstanding at the start of the
        year, so it can never exceed (r + s) * face.
        """
        outstanding, _applied, surviving = self.principal_path(index_paths)
        coupons = (collateral_yield + spread) * outstanding
        return coupons, surviving

    def to_dict(self) -> dict:
        return {"type": "parametric", "city": self.city, "trigger": self.trigger,
                "attach": self.attach, "exhaust": self.exhaust, "tenor": self.tenor,
                "inverted": self.inverted, "aggregate": self.aggregate, "face": self.face}


@dataclass
class WeatherCouponBond:
    """B2: principal-protected bond whose coupon rises in a dry season."""
    city: str
    trigger: str
    strike: float          # K, in mm of the index
    cap: float             # cap on (K - I), in mm
    kappa: float           # coupon added per unit of capped shortfall / scale
    c_fixed: float
    tenor: int
    scale: float = 100.0
    face: float = FACE

    def coupon_rate(self, index_values: np.ndarray) -> np.ndarray:
        shortfall = np.clip(self.strike - np.asarray(index_values, dtype=float), 0.0, self.cap)
        return self.c_fixed + self.kappa * shortfall / self.scale

    def cashflows(self, index_paths: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        idx = np.atleast_2d(np.asarray(index_paths, dtype=float))
        coupons = self.coupon_rate(idx) * self.face
        redemption = np.full(idx.shape[0], self.face)
        return coupons, redemption

    def to_dict(self) -> dict:
        return {"type": "coupon", "city": self.city, "trigger": self.trigger,
                "strike": self.strike, "cap": self.cap, "kappa": self.kappa,
                "c_fixed": self.c_fixed, "tenor": self.tenor, "face": self.face}
