"""Module C, method M3: an independent check on the tree price.

What the spec asked for here was the pathwise dual bounds of Kuhn, Kyprianou
and van Schaik.  That paper was not available while building this, and the
obvious shortcut does not work: freezing one side's policy and optimising the
other with a Longstaff-Schwartz regression gives a *biased* estimate of the
sup/inf, and the bias runs the wrong way for the minimising side, so the result
is not a bound.  Rather than dress that up, this module provides two things
that are actually true:

1. A rigorous bracket that needs no simulation at all,

       G_0  <=  V  <=  min( American value , G_0 + delta ),

   because the holder can always exercise now, the issuer can always cancel
   now, and removing the issuer's right can only help the holder.

2. A policy simulation: both stopping rules are read off the binomial tree and
   then replayed on independent Monte Carlo paths with no regression anywhere.
   Given those two policies the estimate is unbiased, so if it agrees with the
   tree price the tree's policies and its backward induction are consistent
   with a completely separate numerical scheme.  Ties go to the holder, the
   usual convention for Israeli options.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .binomial import payoff, price_game
from .lsm import simulate_gbm


def _interp_boundary(rows: list[dict], key: str, grid: np.ndarray, fill: float) -> np.ndarray:
    ts = np.array([row["t"] for row in rows], dtype=float)
    vals = np.array([np.nan if row[key] is None else row[key] for row in rows], dtype=float)
    ok = np.isfinite(vals)
    if ok.sum() < 2:
        return np.full_like(grid, fill)
    return np.interp(grid, ts[ok], vals[ok], left=vals[ok][0], right=vals[ok][-1])


@dataclass
class Bounds:
    tree: float
    american: float
    intrinsic: float
    lower: float                  # rigorous
    upper: float                  # rigorous
    policy_sim: float
    policy_sim_se: float
    policy_ci: tuple[float, float]
    n_paths: int
    exercise_share: float
    cancel_share: float
    expiry_share: float

    @property
    def tree_inside_bracket(self) -> bool:
        return self.lower - 1e-6 <= self.tree <= self.upper + 1e-6

    @property
    def policy_agrees(self) -> bool:
        return abs(self.policy_sim - self.tree) <= 3.0 * self.policy_sim_se + 0.01 * max(1.0, self.tree)

    def to_dict(self) -> dict:
        return {"tree": self.tree, "american": self.american, "intrinsic": self.intrinsic,
                "lower": self.lower, "upper": self.upper, "policy_sim": self.policy_sim,
                "policy_sim_se": self.policy_sim_se,
                "policy_ci": [float(self.policy_ci[0]), float(self.policy_ci[1])],
                "n_paths": self.n_paths, "exercise_share": self.exercise_share,
                "cancel_share": self.cancel_share, "expiry_share": self.expiry_share,
                "tree_inside_bracket": bool(self.tree_inside_bracket),
                "policy_agrees": bool(self.policy_agrees)}


def bounds(s0: float, strike: float, r: float, q: float, sigma: float, maturity: float,
           kind: str = "put", penalty: float = 0.0, n_paths: int = 80_000, steps: int = 200,
           tree_steps: int = 1000, seed: int = 20261013) -> Bounds:
    tree = price_game(s0, strike, r, q, sigma, maturity, tree_steps, kind, penalty,
                      greeks=False, collect=True)
    grid = np.linspace(0.0, maturity, steps + 1)
    ex_b = _interp_boundary(tree.exercise_boundary, "boundary", grid,
                            -np.inf if kind == "put" else np.inf)
    ca_lo = _interp_boundary(tree.cancellation_band, "lo", grid, np.inf)
    ca_hi = _interp_boundary(tree.cancellation_band, "hi", grid, -np.inf)

    paths = simulate_gbm(s0, r, q, sigma, maturity, steps, n_paths, seed + 1)
    live = np.ones(n_paths, dtype=bool)
    value = np.zeros(n_paths)
    reason = np.zeros(n_paths, dtype=np.int8)        # 1 exercise, 2 cancel, 3 expiry

    for i in range(steps + 1):
        if not live.any():
            break
        spot = paths[:, i]
        g = payoff(spot, strike, kind)
        t = grid[i]
        df = float(np.exp(-r * t))
        if i == steps:
            value = np.where(live, df * g, value)
            reason = np.where(live, 3, reason)
            break
        hits_ex = live & ((spot <= ex_b[i]) if kind == "put" else (spot >= ex_b[i])) & (g > 0)
        hits_ca = live & (spot >= ca_lo[i]) & (spot <= ca_hi[i]) & ~hits_ex
        value = np.where(hits_ex, df * g, value)
        value = np.where(hits_ca, df * (g + penalty), value)
        reason = np.where(hits_ex, 1, np.where(hits_ca, 2, reason))
        live = live & ~hits_ex & ~hits_ca

    mean = float(value.mean())
    se = float(value.std(ddof=1) / np.sqrt(n_paths))
    intrinsic = float(payoff(np.array([s0]), strike, kind)[0])
    return Bounds(
        tree=tree.price, american=tree.american, intrinsic=intrinsic,
        lower=intrinsic, upper=float(min(tree.american, intrinsic + penalty)),
        policy_sim=mean, policy_sim_se=se, policy_ci=(mean - 1.96 * se, mean + 1.96 * se),
        n_paths=int(n_paths),
        exercise_share=float((reason == 1).mean()), cancel_share=float((reason == 2).mean()),
        expiry_share=float((reason == 3).mean()))
