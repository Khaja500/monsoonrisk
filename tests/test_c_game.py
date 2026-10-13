"""Module C acceptance tests (spec C.6 / C.9), with tolerances stated inline."""
import numpy as np
import pytest
from scipy import stats

from src.c_game.binomial import payoff, price_game, price_tree
from src.c_game.dual import bounds
from src.c_game.fd import price_fd
from src.c_game.lsm import price_lsm

S0, R, Q, VOL, T = 22721.95, 0.056, 0.0123, 0.1516, 1.0
REF = dict(s0=S0, r=R, q=Q, sigma=VOL, maturity=T)


def bs_put(s, k, r, q, v, t):
    d1 = (np.log(s / k) + (r - q + 0.5 * v * v) * t) / (v * np.sqrt(t))
    d2 = d1 - v * np.sqrt(t)
    return k * np.exp(-r * t) * stats.norm.cdf(-d2) - s * np.exp(-q * t) * stats.norm.cdf(-d1)


def test_european_tree_matches_black_scholes():
    tree = price_tree(S0, S0, R, Q, VOL, T, 4000, "put", 0.0, "european")["price"]
    assert tree == pytest.approx(bs_put(S0, S0, R, Q, VOL, T), rel=5e-4)


def test_zero_penalty_gives_intrinsic_value():
    """With delta = 0 the issuer cancels at once for the intrinsic value."""
    for k_mult in (0.95, 1.0, 1.05):
        k = k_mult * S0
        price = price_tree(S0, k, R, Q, VOL, T, 500, "put", 0.0, "game")["price"]
        assert price == pytest.approx(max(k - S0, 0.0), abs=1e-6)


def test_large_penalty_converges_to_american():
    game = price_tree(S0, S0, R, Q, VOL, T, 800, "put", 1e9, "game")["price"]
    american = price_tree(S0, S0, R, Q, VOL, T, 800, "put", 0.0, "american")["price"]
    assert game == pytest.approx(american, rel=1e-12)


def test_value_is_bracketed_everywhere():
    for k_mult in (0.95, 1.0, 1.05):
        for pen in (0.0, 0.01, 0.03, 0.05):
            res = price_game(S0, k_mult * S0, R, Q, VOL, T, 600, "put", pen * S0,
                             greeks=False, collect=False)
            intrinsic = max(k_mult * S0 - S0, 0.0)
            assert intrinsic - 1e-6 <= res.price <= min(res.american, intrinsic + pen * S0) + 1e-6


def test_value_is_non_decreasing_in_penalty():
    prices = [price_tree(S0, S0, R, Q, VOL, T, 600, "put", p * S0, "game")["price"]
              for p in (0.0, 0.005, 0.01, 0.02, 0.04, 0.08)]
    assert all(b >= a - 1e-9 for a, b in zip(prices, prices[1:]))


def test_american_at_least_european_at_least_game():
    res = price_game(S0, 1.05 * S0, R, Q, VOL, T, 600, "put", 0.02 * S0, greeks=False)
    assert res.american >= res.european - 1e-6
    assert res.american >= res.price - 1e-6
    assert res.cancellation_value >= -1e-6


def test_lsm_agrees_with_tree():
    """Compared at a matched monitoring frequency.

    The number of decision dates is part of the contract here: with fewer dates
    the issuer has fewer chances to cancel and the option is worth more to the
    holder, so a 200-step Monte Carlo is compared against a 200-step tree, not
    against a 3,000-step one.  Tolerance: 3 standard errors plus 1% of the tree
    price.
    """
    steps = 200
    for k_mult, pen in ((1.0, 0.03), (1.05, 0.02), (0.95, 0.02), (1.05, 0.05)):
        k, delta = k_mult * S0, pen * S0
        tree = price_tree(S0, k, R, Q, VOL, T, steps, "put", delta, "game")["price"]
        mc = price_lsm(S0, k, R, Q, VOL, T, "put", delta, n_paths=120_000, steps=steps)
        assert abs(mc.price - tree) <= 3 * mc.stderr + 0.01 * max(tree, 1.0), (k_mult, pen)


def test_hard_case_methods_stay_within_five_percent():
    """The out-of-the-money put with a 1% penalty is the worst case for every
    method: the free boundary sits on the payoff kink, the tree oscillates with
    the step count and the regression has to resolve a narrow cancellation
    region.  Recorded here so the disagreement is visible rather than hidden."""
    k, delta = 0.95 * S0, 0.01 * S0
    tree = price_tree(S0, k, R, Q, VOL, T, 200, "put", delta, "game")["price"]
    mc = price_lsm(S0, k, R, Q, VOL, T, "put", delta, n_paths=120_000, steps=200)
    pde = price_fd(S0, k, R, Q, VOL, T, "put", delta, "game", n_space=900, n_time=900)["price"]
    assert abs(mc.price - tree) <= 0.05 * tree
    assert abs(pde - tree) <= 0.05 * tree


def test_finite_difference_agrees_with_tree():
    """Both schemes resolve a free boundary sitting on the payoff kink, so the
    agreed tolerance is 1% at the money / in the money."""
    for k_mult, pen in ((1.0, 0.03), (1.05, 0.02), (1.0, 0.06)):
        k, delta = k_mult * S0, pen * S0
        tree = price_tree(S0, k, R, Q, VOL, T, 3000, "put", delta, "game")["price"]
        pde = price_fd(S0, k, R, Q, VOL, T, "put", delta, "game", n_space=900, n_time=900)["price"]
        assert abs(pde - tree) <= 0.01 * max(tree, 1.0)


def test_european_finite_difference_matches_black_scholes():
    pde = price_fd(S0, S0, R, Q, VOL, T, "put", 0.0, "european", n_space=800, n_time=800)["price"]
    assert pde == pytest.approx(bs_put(S0, S0, R, Q, VOL, T), rel=1e-3)


def test_rigorous_bracket_contains_tree_price():
    b = bounds(S0, 1.05 * S0, R, Q, VOL, T, "put", 0.02 * S0, n_paths=20_000, steps=50,
               tree_steps=400)
    assert b.tree_inside_bracket


def test_tree_convergence_is_stable():
    prices = [price_tree(S0, 1.05 * S0, R, Q, VOL, T, n, "put", 0.02 * S0, "game")["price"]
              for n in (500, 1000, 2000, 4000)]
    assert max(prices) - min(prices) <= 0.01 * np.mean(prices)


def test_payoff_helpers():
    assert payoff(np.array([90.0]), 100.0, "put")[0] == 10.0
    assert payoff(np.array([110.0]), 100.0, "call")[0] == 10.0
    with pytest.raises(ValueError):
        payoff(np.array([1.0]), 1.0, "straddle")


def test_averaged_lattice_price_reports_its_own_spread():
    """The double-obstacle lattice oscillates; averaging must come with the spread."""
    from src.c_game.binomial import averaged_price

    out = averaged_price(S0, 0.95 * S0, R, Q, VOL, T, "put", 0.01 * S0,
                         steps_list=list(range(600, 1201, 200)))
    assert out["min"] <= out["price"] <= out["max"]
    assert out["sd"] > 0
    assert len(out["values"]) == len(out["steps"])


def test_terminal_smoothing_does_not_change_the_answer_materially():
    """Recorded because it is a negative result worth keeping: the oscillation
    on the hard contract comes from the free boundary, not the payoff kink."""
    raw = price_tree(S0, 0.95 * S0, R, Q, VOL, T, 800, "put", 0.01 * S0, "game", smooth=False)
    smoothed = price_tree(S0, 0.95 * S0, R, Q, VOL, T, 800, "put", 0.01 * S0, "game", smooth=True)
    assert abs(raw["price"] - smoothed["price"]) < 0.05
