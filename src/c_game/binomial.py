"""Module C, method M1: CRR tree for an Israeli (game) option.

The holder may exercise for G_t; the issuer may cancel for H_t = G_t + delta.
The pair of stopping times is a Dynkin game and the discrete recursion is

    V_N = G_N
    V_i = min( H_i , max( G_i , C_i ) )

with C_i the discounted risk-neutral continuation value.  Setting the issuer's
payoff out of reach recovers the American value, which is what the delta -> inf
limit test compares against.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


def payoff(spot: np.ndarray, strike: float, kind: str) -> np.ndarray:
    if kind == "put":
        return np.maximum(strike - spot, 0.0)
    if kind == "call":
        return np.maximum(spot - strike, 0.0)
    raise ValueError(kind)


@dataclass
class GameResult:
    price: float
    american: float
    european: float
    cancellation_value: float
    kind: str
    strike: float
    maturity: float
    penalty: float
    steps: int
    exercise_boundary: list[dict] = field(default_factory=list)
    cancellation_band: list[dict] = field(default_factory=list)
    greeks: dict = field(default_factory=dict)
    checks: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def _tree_params(r: float, q: float, sigma: float, dt: float) -> tuple[float, float, float, float]:
    u = float(np.exp(sigma * np.sqrt(dt)))
    d = 1.0 / u
    p = (np.exp((r - q) * dt) - d) / (u - d)
    return u, d, float(p), float(np.exp(-r * dt))


def price_tree(s0: float, strike: float, r: float, q: float, sigma: float, maturity: float,
               steps: int, kind: str = "put", penalty: float = 0.0,
               style: str = "game", collect: bool = False) -> dict:
    """One backward induction over a CRR tree.

    `style` selects the recursion: "game" (both rights), "american" (holder
    only) or "european" (neither).  With `collect` the holder's exercise region
    and the issuer's cancellation region are recorded per time step.
    """
    dt = maturity / steps
    u, d, p, disc = _tree_params(r, q, sigma, dt)
    if not 0.0 < p < 1.0:
        raise ValueError(f"tree probability {p:.4f} outside (0,1): raise steps or lower sigma")

    j = np.arange(steps + 1)
    spot = s0 * u ** (steps - j) * d ** j          # j = number of down moves
    values = payoff(spot, strike, kind)

    exercise_boundary, cancellation_band = [], []
    for i in range(steps - 1, -1, -1):
        cont = disc * (p * values[:-1] + (1 - p) * values[1:])
        spot = spot[:-1] / u
        g = payoff(spot, strike, kind)
        if style == "european":
            values = cont
            continue
        hold = np.maximum(g, cont)
        if style == "american":
            values = hold
        else:
            h = g + penalty
            values = np.minimum(h, hold)
        if collect and style == "game":
            t = i * dt
            ex = spot[(g >= cont - 1e-12) & (g > 0)]
            ca = spot[cont > g + penalty + 1e-12]
            exercise_boundary.append({
                "t": float(t),
                "boundary": float(ex.max()) if kind == "put" and len(ex) else (
                    float(ex.min()) if len(ex) else None)})
            cancellation_band.append({
                "t": float(t),
                "lo": float(ca.min()) if len(ca) else None,
                "hi": float(ca.max()) if len(ca) else None})
    out = {"price": float(values[0])}
    if collect:
        out["exercise_boundary"] = list(reversed(exercise_boundary))
        out["cancellation_band"] = list(reversed(cancellation_band))
    return out


def price_game(s0: float, strike: float, r: float, q: float, sigma: float, maturity: float,
               steps: int = 2000, kind: str = "put", penalty: float = 0.0,
               greeks: bool = True, collect: bool = True) -> GameResult:
    game = price_tree(s0, strike, r, q, sigma, maturity, steps, kind, penalty, "game", collect)
    american = price_tree(s0, strike, r, q, sigma, maturity, steps, kind, 0.0, "american")["price"]
    european = price_tree(s0, strike, r, q, sigma, maturity, steps, kind, 0.0, "european")["price"]

    g = {}
    if greeks:
        h = 0.01 * s0
        f = lambda s, sig=sigma, rr=r, T=maturity: price_tree(
            s, strike, rr, q, sig, T, max(steps // 2, 200), kind, penalty, "game")["price"]
        up, dn, mid = f(s0 + h), f(s0 - h), f(s0)
        g = {
            "delta": (up - dn) / (2 * h),
            "gamma": (up - 2 * mid + dn) / (h * h),
            "vega_per_1pct": (f(s0, sigma + 0.01) - f(s0, sigma - 0.01)) / 2.0,
            "rho_per_1pct": (f(s0, sigma, r + 0.01) - f(s0, sigma, r - 0.01)) / 2.0,
            "theta_per_day": (f(s0, sigma, r, max(maturity - 1 / 365, 1e-4)) - mid),
        }

    intrinsic = float(payoff(np.array([s0]), strike, kind)[0])
    checks = {
        "lower_bound_intrinsic": bool(game["price"] >= intrinsic - 1e-6),
        "upper_bound_american": bool(game["price"] <= american + 1e-6),
        "upper_bound_cancellation": bool(game["price"] <= intrinsic + penalty + 1e-6),
        "american_ge_european": bool(american >= european - 1e-6),
    }
    return GameResult(
        price=game["price"], american=american, european=european,
        cancellation_value=american - game["price"], kind=kind, strike=strike,
        maturity=maturity, penalty=penalty, steps=steps,
        exercise_boundary=game.get("exercise_boundary", []),
        cancellation_band=game.get("cancellation_band", []),
        greeks=g, checks=checks)


def convergence(s0: float, strike: float, r: float, q: float, sigma: float, maturity: float,
                step_grid: list[int], kind: str = "put", penalty: float = 0.0) -> list[dict]:
    out = []
    for n in step_grid:
        out.append({"steps": int(n),
                    "price": price_tree(s0, strike, r, q, sigma, maturity, n, kind,
                                        penalty, "game")["price"]})
    return out
