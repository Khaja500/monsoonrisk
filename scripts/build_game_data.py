"""Build docs/data/game.json: Module C prices, boundaries, convergence and the
validation suite, using the dated NIFTY 50 inputs in config/game_option.yaml.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from src.c_game.binomial import averaged_price, convergence, price_game, price_tree
from src.c_game.dual import bounds
from src.c_game.fd import price_fd
from src.c_game.lsm import price_lsm
from src.c_game.nifty import load_inputs
from src.common.paths import SITE_DATA, ensure_dirs, load_config


def penalty_threshold(s0, k, r, q, sigma, T, kind, lo=0.0, hi=0.30, tol=1e-4) -> float:
    """Smallest penalty (as a fraction of S0) at which the issuer's cancellation
    right is worthless, i.e. the game value reaches the American value."""
    american = price_tree(s0, k, r, q, sigma, T, 800, kind, 0.0, "american")["price"]
    f = lambda d: price_tree(s0, k, r, q, sigma, T, 800, kind, d * s0, "game")["price"]
    if f(hi) < american - 1e-6:
        return float("nan")
    while hi - lo > tol:
        mid = 0.5 * (lo + hi)
        if f(mid) >= american - 1e-6:
            hi = mid
        else:
            lo = mid
    return float(hi)


def main() -> None:
    ensure_dirs()
    cfg = load_config("game_option")
    num, con, mkt = cfg["numerics"], cfg["contract"], cfg["market"]
    inp = load_inputs()
    s0, r, q, sigma = inp.s0, inp.r, inp.q, inp.sigma
    kind = con["kind"]
    seed = int(num["seed"])

    # Reference contract: a 5% in-the-money one-year put with a 2% penalty.
    # The at-the-money contract is degenerate - its price is exactly the penalty
    # until the penalty crosses the threshold below - so it is reported as a
    # separate finding rather than used as the reference.
    ref_strike_pct, ref_T, ref_pen = 1.05, 1.0, 0.02
    ref_strike = ref_strike_pct * s0
    ref = price_game(s0, ref_strike, r, q, sigma, ref_T, int(num["binomial_steps"]), kind,
                     ref_pen * s0, greeks=True, collect=True)
    atm = price_game(s0, s0, r, q, sigma, ref_T, int(num["binomial_steps"]), kind,
                     ref_pen * s0, greeks=False, collect=False)

    # price surface
    table = []
    for kp in con["strikes_pct"]:
        for T in con["tenors_years"]:
            for pen in con["penalty_pct_of_s0"]:
                res = price_game(s0, kp * s0, r, q, sigma, T, 1200, kind, pen * s0,
                                 greeks=False, collect=False)
                table.append({"strike_pct": kp, "strike": kp * s0, "tenor": T,
                              "penalty_pct": pen, "price": res.price,
                              "american": res.american, "european": res.european,
                              "cancellation_value": res.cancellation_value})

    vol_grid = []
    for vol in np.round(np.arange(0.08, 0.361, 0.02), 4):
        row = {"sigma": float(vol)}
        for pen in (0.01, 0.02, 0.05):
            row[f"p{int(pen*100)}"] = price_tree(s0, ref_strike, r, q, float(vol), ref_T,
                                                 800, kind, pen * s0, "game")["price"]
        row["american"] = price_tree(s0, ref_strike, r, q, float(vol), ref_T, 800, kind,
                                     0.0, "american")["price"]
        vol_grid.append(row)

    penalty_curve_itm = [
        {"penalty_pct": float(pen),
         "price": price_tree(s0, ref_strike, r, q, sigma, ref_T, 1200, kind, float(pen) * s0,
                             "game")["price"]}
        for pen in np.round(np.arange(0.0, 0.0801, 0.0025), 5)]

    # Two penalty curves: one struck at spot (where the issuer cancels at once)
    # and one struck 5% in the money (the reference contract).
    american_ref = price_tree(s0, ref_strike, r, q, sigma, ref_T, 1200, kind, 0.0, "american")["price"]
    penalty_curve = [
        {"penalty_pct": float(pen),
         "price": price_tree(s0, s0, r, q, sigma, ref_T, 1200, kind, float(pen) * s0,
                             "game")["price"]}
        for pen in np.round(np.arange(0.0, 0.0801, 0.0025), 5)]

    # method comparison at a matched monitoring frequency
    methods = []
    for kp, pen in ((1.0, 0.03), (1.05, 0.02), (0.95, 0.02), (1.05, 0.05), (0.95, 0.01)):
        k, delta = kp * s0, pen * s0
        steps = int(num["lsm_steps"])
        tree_matched = price_tree(s0, k, r, q, sigma, ref_T, steps, kind, delta, "game")["price"]
        # A single fine tree is not a reference: the double-obstacle lattice
        # oscillates with the step count.  Average a band of resolutions and
        # publish the spread as the numerical uncertainty that remains.
        avg = averaged_price(s0, k, r, q, sigma, ref_T, kind, delta,
                             steps_list=list(range(1500, 2501, 100)))
        tree_fine = avg["price"]
        mc = price_lsm(s0, k, r, q, sigma, ref_T, kind, delta, n_paths=int(num["lsm_paths"]),
                       steps=steps, degree=int(num["lsm_basis_degree"]), seed=seed)
        pde = price_fd(s0, k, r, q, sigma, ref_T, kind, delta, "game", n_space=2000, n_time=2000)
        br = bounds(s0, k, r, q, sigma, ref_T, kind, delta, n_paths=40_000, steps=200,
                    tree_steps=1200, seed=seed)
        methods.append({
            "strike_pct": kp, "penalty_pct": pen,
            "tree_matched_steps": tree_matched, "tree_averaged": tree_fine,
            "tree_averaged_sd": avg["sd"], "tree_averaged_range": [avg["min"], avg["max"]],
            "lsm": mc.price, "lsm_se": mc.stderr, "lsm_ci": [mc.ci[0], mc.ci[1]],
            "pde": pde["price"], "steps": steps,
            "bracket_lower": br.lower, "bracket_upper": br.upper,
            "tree_inside_bracket": br.tree_inside_bracket,
            "lsm_vs_tree_pct": 100.0 * (mc.price - tree_matched) / max(tree_matched, 1e-9),
            "pde_vs_tree_pct": 100.0 * (pde["price"] - tree_fine) / max(tree_fine, 1e-9),
        })

    # validation suite
    checks = []

    def add(name, passed, detail):
        checks.append({"name": name, "pass": bool(passed), "detail": detail})

    from scipy.stats import norm
    sqt = sigma * np.sqrt(ref_T)
    d1 = (np.log(s0 / ref_strike) + (r - q + 0.5 * sigma ** 2) * ref_T) / sqt
    d2 = d1 - sqt
    bs = ref_strike * np.exp(-r * ref_T) * norm.cdf(-d2) - s0 * np.exp(-q * ref_T) * norm.cdf(-d1)
    tree_euro = price_tree(s0, ref_strike, r, q, sigma, ref_T, 4000, kind, 0.0, "european")["price"]
    add("European tree matches Black-Scholes", abs(tree_euro - bs) < 1e-3 * bs,
        f"tree {tree_euro:.3f} vs closed form {bs:.3f} (put struck at {ref_strike:.0f})")
    zero = price_tree(s0, 1.05 * s0, r, q, sigma, ref_T, 500, kind, 0.0, "game")["price"]
    add("Zero penalty gives intrinsic value", abs(zero - 0.05 * s0) < 1e-6,
        f"V = {zero:.4f}, intrinsic = {0.05 * s0:.4f}")
    big = price_tree(s0, s0, r, q, sigma, ref_T, 800, kind, 1e9, "game")["price"]
    amer = price_tree(s0, s0, r, q, sigma, ref_T, 800, kind, 0.0, "american")["price"]
    add("Large penalty converges to the American price", abs(big - amer) < 1e-9,
        f"game {big:.4f} vs American {amer:.4f}")
    prices = [price_tree(s0, s0, r, q, sigma, ref_T, 600, kind, p * s0, "game")["price"]
              for p in (0.0, 0.005, 0.01, 0.02, 0.04, 0.08)]
    add("Value is non-decreasing in the penalty", all(b >= a - 1e-9 for a, b in zip(prices, prices[1:])),
        " <= ".join(f"{p:.1f}" for p in prices))
    add("Value stays inside [G, min(American, G+delta)]",
        all(m["tree_inside_bracket"] for m in methods),
        "checked at five strike/penalty combinations")
    worst_lsm = max(abs(m["lsm_vs_tree_pct"]) for m in methods)
    add("Monte Carlo agrees with the tree at matched monitoring frequency", worst_lsm < 5.0,
        f"largest gap {worst_lsm:.2f}% (out-of-the-money with a 1% penalty is the worst case)")
    worst_pde = max(abs(m["pde_vs_tree_pct"]) for m in methods)
    add("Finite differences agree with the averaged tree", worst_pde < 5.0,
        f"largest gap {worst_pde:.2f}%")
    worst_osc = max(200.0 * m["tree_averaged_sd"] / max(m["tree_averaged"], 1e-9)
                    for m in methods)
    add("Lattice oscillation is measured, not hidden", worst_osc < 5.0,
        f"largest 2-sigma swing across step counts {worst_osc:.2f}% of price")
    conv = convergence(s0, ref_strike, r, q, sigma, ref_T, num["convergence_steps"], kind,
                       ref_pen * s0)
    conv_atm = convergence(s0, s0, r, q, sigma, ref_T, num["convergence_steps"], kind,
                           ref_pen * s0)
    spread = max(c["price"] for c in conv[-3:]) - min(c["price"] for c in conv[-3:])
    add("Tree price is stable in the step count", spread <= 0.02 * max(conv[-1]["price"], 1.0),
        f"last three step counts spread by {spread:.4f}")

    out = {
        "meta": {"asof": inp.asof, "sources": mkt, "numerics": num, "contract": con,
                 "realised_vol_note": mkt["realised_vol_note"]},
        "inputs": inp.to_dict(),
        "reference": {"strike": ref_strike, "strike_pct": ref_strike_pct, "tenor": ref_T,
                      "penalty_pct": ref_pen, **ref.to_dict()},
        "atm_finding": {
            "strike": s0, "tenor": ref_T, "penalty_pct": ref_pen,
            "price": atm.price, "penalty_value": ref_pen * s0,
            "american": atm.american,
            "threshold_pct": penalty_threshold(s0, s0, r, q, sigma, ref_T, kind),
            "statement": ("With the strike at spot the holder's payoff is zero and the "
                          "issuer's time value is not, so the issuer cancels at once: the "
                          "price is exactly the penalty, for every penalty below the "
                          "threshold, and the American price above it."),
        },
        "price_table": table,
        "vol_grid": vol_grid,
        "penalty_curve": penalty_curve,
        "penalty_curve_itm": penalty_curve_itm,
        "american_reference": american_ref,
        "penalty_threshold_pct": penalty_threshold(s0, ref_strike, r, q, sigma, ref_T, kind),
        "convergence": conv,
        "convergence_atm": conv_atm,
        "methods": methods,
        "checks": checks,
    }
    path = os.path.join(SITE_DATA, "game.json")
    with open(path, "w") as fh:
        json.dump(out, fh, separators=(",", ":"), allow_nan=False, default=str)
    print("wrote", path, round(os.path.getsize(path) / 1e3, 1), "kB")
    print("all checks pass:", all(c["pass"] for c in checks))
    for c in checks:
        print(("  PASS " if c["pass"] else "  FAIL "), c["name"], "--", c["detail"])


if __name__ == "__main__":
    main()
