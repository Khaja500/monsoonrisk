"""Module C, method M4: Crank-Nicolson finite differences with two obstacles.

The game option is a double-obstacle problem: the value has to stay inside
[G, H] = [payoff, payoff + penalty] at every point, with the holder pushing it
up and the issuer pushing it down.  Each time step solves the Black-Scholes
operator on a log-price grid and then projects the solution back into the
corridor (operator splitting).  This is a genuinely different discretisation
from the tree, so agreement between the two is a real check.
"""
from __future__ import annotations

import numpy as np

from .binomial import payoff


def _thomas(lower: np.ndarray, diag: np.ndarray, upper: np.ndarray, rhs: np.ndarray) -> np.ndarray:
    n = len(diag)
    c, d = np.empty(n), np.empty(n)
    c[0] = upper[0] / diag[0]
    d[0] = rhs[0] / diag[0]
    for i in range(1, n):
        denom = diag[i] - lower[i] * c[i - 1]
        c[i] = upper[i] / denom if i < n - 1 else 0.0
        d[i] = (rhs[i] - lower[i] * d[i - 1]) / denom
    x = np.empty(n)
    x[-1] = d[-1]
    for i in range(n - 2, -1, -1):
        x[i] = d[i] - c[i] * x[i + 1]
    return x


def price_fd(s0: float, strike: float, r: float, q: float, sigma: float, maturity: float,
             kind: str = "put", penalty: float = 0.0, style: str = "game",
             n_space: int = 1200, n_time: int = 1200, width: float = 6.0) -> dict:
    """Price on a log-price grid spanning `width` standard deviations each way."""
    span = width * sigma * np.sqrt(maturity) + 1e-6
    x = np.linspace(np.log(s0) - span, np.log(s0) + span, n_space + 1)
    dx = x[1] - x[0]
    dt = maturity / n_time
    spot = np.exp(x)
    g = payoff(spot, strike, kind)
    h = g + penalty
    v = g.copy()

    nu = r - q - 0.5 * sigma ** 2
    a = 0.5 * sigma ** 2 / dx ** 2
    b = nu / (2 * dx)
    # Crank-Nicolson coefficients for the interior nodes
    lo_i = -0.5 * dt * (a - b)
    di_i = 1.0 + dt * (a + 0.5 * r)
    up_i = -0.5 * dt * (a + b)
    lo_e = 0.5 * dt * (a - b)
    di_e = 1.0 - dt * (a + 0.5 * r)
    up_e = 0.5 * dt * (a + b)

    n = n_space - 1
    lower = np.full(n, lo_i)
    diag = np.full(n, di_i)
    upper = np.full(n, up_i)

    for k in range(n_time):
        t_left = maturity - (k + 1) * dt
        rhs = lo_e * v[:-2] + di_e * v[1:-1] + up_e * v[2:]
        # Dirichlet edges: deep ITM/OTM values follow the discounted payoff.
        if kind == "put":
            v_low = strike * np.exp(-r * t_left) - spot[0] * np.exp(-q * t_left)
            v_high = 0.0
        else:
            v_low = 0.0
            v_high = spot[-1] * np.exp(-q * t_left) - strike * np.exp(-r * t_left)
        if style == "game":
            v_low = min(max(v_low, g[0]), h[0])
            v_high = min(max(v_high, g[-1]), h[-1])
        else:
            v_low, v_high = max(v_low, g[0]), max(v_high, g[-1])
        rhs[0] -= lo_i * v_low
        rhs[-1] -= up_i * v_high
        inner = _thomas(lower, diag, upper, rhs)
        v = np.concatenate([[v_low], inner, [v_high]])
        if style == "american":
            v = np.maximum(v, g)
        elif style == "game":
            v = np.minimum(h, np.maximum(v, g))

    return {"price": float(np.interp(np.log(s0), x, v)),
            "grid": {"n_space": n_space, "n_time": n_time, "span_sd": width}}
