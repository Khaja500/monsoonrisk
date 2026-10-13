"""Module B acceptance tests (spec B.9)."""
import numpy as np
import pytest
from scipy import stats

from src.b_bonds.contracts import FACE, ParametricBond, WeatherCouponBond
from src.b_bonds.premium import PremiumRule, distorted_expectation, wang_weights
from src.b_bonds.pricer import price_coupon_bond, price_parametric, quadrature_expected_loss


class FrozenDist:
    """Minimal stand-in for SeasonDistribution."""

    def __init__(self, dist, sample):
        self.dist = dist
        self._sample = np.asarray(sample, dtype=float)

    def burn_sample(self):
        return self._sample


def gamma_dist(mean=340.0, sd=85.0, n=60, seed=3):
    """A frozen gamma with a sample drawn from it, standing in for a fitted index."""
    shape = (mean / sd) ** 2
    scale = sd ** 2 / mean
    dist = stats.gamma(shape, scale=scale)
    return FrozenDist(dist, dist.rvs(size=n, random_state=np.random.default_rng(seed)))


def test_binary_trigger_expected_loss_equals_trigger_probability():
    d = gamma_dist()
    bond = ParametricBond("x", "MAX3", attach=450.0, exhaust=450.0, tenor=1)
    res = price_parametric(bond, d, PremiumRule.r1(1.0), 0.056, 0.056, "mc", 200_000)
    assert res.expected_loss_annual == pytest.approx(float(d.dist.sf(450.0)), abs=3e-3)


def test_raising_attachment_lowers_expected_loss():
    d = gamma_dist()
    rule = PremiumRule.r1(1.0)
    els = []
    for attach in (380.0, 420.0, 460.0):
        bond = ParametricBond("x", "MAX3", attach, 600.0, 1)
        els.append(price_parametric(bond, d, rule, 0.056, 0.056, "mc", 100_000).expected_loss_annual)
    assert els[0] > els[1] > els[2]


def test_quadrature_matches_monte_carlo_within_three_standard_errors():
    d = gamma_dist()
    bond = ParametricBond("x", "MAX3", 400.0, 550.0, 1)
    res = price_parametric(bond, d, PremiumRule.r1(1.0), 0.056, 0.056, "analytic", 400_000)
    quad = quadrature_expected_loss(bond, d)
    assert abs(quad - res.expected_loss_annual) <= 3 * res.standard_error + 1e-4


def test_price_is_par_at_fair_spread_under_wang():
    d = gamma_dist()
    bond = ParametricBond("x", "MAX3", 400.0, 550.0, 3)
    res = price_parametric(bond, d, PremiumRule.wang(0.25), 0.056, 0.056, "mc", 100_000)
    assert res.price_at_fair_spread == pytest.approx(FACE, abs=1e-6)


def test_zero_premium_gives_zero_spread_under_r1():
    d = gamma_dist()
    bond = ParametricBond("x", "MAX3", 400.0, 550.0, 1)
    res = price_parametric(bond, d, PremiumRule.r1(0.0), 0.056, 0.056, "mc", 50_000)
    assert res.fair_spread == pytest.approx(0.0, abs=1e-12)


def test_spread_rises_with_expected_loss_for_r1():
    d = gamma_dist()
    low = price_parametric(ParametricBond("x", "MAX3", 460.0, 600.0, 1), d,
                           PremiumRule.r1(2.0), 0.056, 0.056, "mc", 100_000)
    high = price_parametric(ParametricBond("x", "MAX3", 380.0, 600.0, 1), d,
                            PremiumRule.r1(2.0), 0.056, 0.056, "mc", 100_000)
    assert high.fair_spread > low.fair_spread


def test_principal_never_negative_and_coupon_capped():
    bond = ParametricBond("x", "MAX3", 100.0, 200.0, 3)
    idx = np.array([[1000.0, 1000.0, 1000.0], [150.0, 160.0, 170.0]])
    outstanding, applied, surviving = bond.principal_path(idx)
    assert (outstanding >= 0).all() and (surviving >= 0).all()
    assert applied.sum(axis=1).max() <= FACE + 1e-12
    coupons, _ = bond.cashflows(idx, 0.056, 0.03)
    assert coupons.max() <= (0.056 + 0.03) * FACE + 1e-12


def test_inverted_trigger_pays_on_dry_seasons():
    bond = ParametricBond("x", "SEAS_TOTAL", attach=600.0, exhaust=300.0, tenor=1, inverted=True)
    assert bond.loss_fraction(np.array([700.0]))[0] == 0.0
    assert bond.loss_fraction(np.array([450.0]))[0] == pytest.approx(0.5)
    assert bond.loss_fraction(np.array([200.0]))[0] == 1.0


def test_wang_weights_are_a_probability_measure_and_shift_mass_to_the_tail():
    w0 = wang_weights(50, 0.0)
    assert w0.sum() == pytest.approx(1.0)
    assert np.allclose(w0, 1 / 50, atol=1e-9)
    sample = np.linspace(0.0, 1.0, 50)
    assert distorted_expectation(sample, 0.3) > distorted_expectation(sample, 0.0)
    assert distorted_expectation(sample, 0.0) == pytest.approx(sample.mean(), abs=1e-9)


def test_coupon_bond_pays_more_in_dry_years():
    d = gamma_dist(mean=750.0, sd=300.0)
    bond = WeatherCouponBond("x", "SEAS_TOTAL", strike=700.0, cap=400.0, kappa=0.06,
                             c_fixed=0.055, tenor=3)
    assert bond.coupon_rate(np.array([900.0]))[0] == pytest.approx(0.055)
    assert bond.coupon_rate(np.array([500.0]))[0] > 0.055
    res = price_coupon_bond(bond, d, 0.056, "mc", 50_000)
    assert res["price"] > 0 and 0.0 < res["prob_above_fixed"] < 1.0


def test_parameter_uncertainty_band_brackets_the_point_estimate():
    """45 seasons do not pin down a 1-in-100 attachment; the band must say so."""
    from src.b_bonds.pricer import price_with_parameter_uncertainty

    d = gamma_dist(n=45)
    bond = ParametricBond("x", "MAX3", float(d.dist.ppf(0.90)), float(d.dist.ppf(0.99)), 1)
    out = price_with_parameter_uncertainty(bond, d, PremiumRule.wang(0.25), 0.056, 0.056,
                                           n_boot=60, n_paths=8000)
    assert out["n_boot"] >= 40
    for key in ("expected_loss_annual", "fair_spread", "prob_attach"):
        band, point = out[key], out["point_estimate"][key]
        assert band["p05"] <= point <= band["p95"], key
        assert band["p95"] > band["p05"]
    curve = out["exceedance_band"]
    assert all(row["lo"] <= row["mid"] <= row["hi"] + 1e-12 for row in curve)
    assert curve[0]["hi"] >= curve[-1]["hi"]        # exceedance is non-increasing
