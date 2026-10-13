# MonsoonRisk — methodology

This note says what each module computes, what it rests on, and what it cannot
be trusted for. The numbers on the site come from `scripts/build_weather_data.py`
and `scripts/build_game_data.py`; every control on the page re-prices with the
same models re-implemented in `docs/pricing.js`.

## Module A — rainfall indices

**Data.** IMD's 0.25° gridded daily rainfall for 1981–2025, read with `imdlib`,
one cell per city (Mumbai 19.00 N 73.00 E, Chennai 13.25 N 80.25 E, Bengaluru
13.00 N 77.50 E — the nearest cells with complete land data). The 2026 season is
not in IMD's archive yet and IMD's real-time server did not answer, so 2026 days
come from NASA POWER's corrected precipitation and are flagged provisional
everywhere they are used.

**Normals.** The daily normal is the 1991–2020 mean for each calendar day,
smoothed with a centred 15-day moving average and then rescaled over the season
so that it sums exactly to the contract anchor.

**Bias correction.** A grid cell is not a station. Mumbai's cell averages
2,723 mm over June–September against the 2,206.7 mm the contract settles on, so
every source is scaled by its own 1991–2020 seasonal normal onto the published
station normal: ×0.810 for the Mumbai grid, ×1.009 for Chennai, ×1.000 for
Bengaluru (no station normal was verified). This fixes the level, not the shape
of the distribution.

**Indices.** Per season: `CDR` (cumulative deviation from the normal),
`SEAS_TOTAL`, `MAX1`, `MAX3` and `WET_DAYS`. Because the normal is rescaled to
the anchor, `anchor + CDR = SEAS_TOTAL` exactly, which is the identity the
exchange's spot is built on.

**Distributions.** Candidate families are fitted by maximum likelihood and
ranked by AIC, with a Kolmogorov–Smirnov statistic and a percentile bootstrap of
the empirical quantiles reported alongside. Block maxima get a GEV. Everything
rests on 45 seasons, which is thin in the tail; the bootstrap intervals are in
the exported data.

**Season windows.** Mumbai is 1 Jun – 30 Sep because RAINMUMBAI is. Chennai is
1 Oct – 31 Dec, IMD's north-east monsoon. Bengaluru's window is chosen from the
data — the fewest months capturing at least 75% of annual rainfall, which is
1 Jun – 30 Nov at 78.7%.

## Module B — futures and catastrophe bonds

**The index future.** NCDEX publishes a daily anchored cumulative deviation, and
the contract for a month settles on that spot just after month end. Fair value is

    F = spot + (factor − 1) × remaining normal + trend + λ × remaining σ

Note what the first term implies: with a climatological forecast (factor = 1, no
trend, no premium) the fair value *is* the current spot, so the future is a
martingale under climatology and every departure from spot must be argued for.
The trend is Theil–Sen on seasonal totals, used only when a Mann–Kendall test
gives p < 0.10, and in the backtest it is refitted each year on prior seasons so
it never sees its own answer.

**Bonds.** A principal-at-risk bond writes down principal as
`min(1, max(0, (I − A)/(E − A)))` each season (inverted for drought), pays
`(r + s)` on the principal still outstanding, and redeems what survives. A
principal-protected variant pays a coupon that rises with a capped rainfall
shortfall. Three methods price every bond — burn analysis on the observed
seasons, quadrature against the fitted density, and Monte Carlo with antithetic
variates — and they are published side by side.

**Risk premium.** The index is not tradeable, the market is incomplete, and
India has no catastrophe bond market to calibrate against. Three rules are
reported together: an expected-loss multiple, a Wang transform of the loss
distribution, and a standard-deviation loading. Under the Wang rule the pricing
measure re-weights whole simulated paths by their total discounted loss, so
every quantity of a path is averaged under one measure, and the fair spread is
the one that prices the bond at par under it.

## Module C — the Israeli (game) option

The holder may exercise for `G`; the issuer may cancel for `H = G + δ`. The pair
of stopping times is a Dynkin game and the discrete recursion is
`V_N = G_N`, `V_i = min(H_i, max(G_i, C_i))`.

Four methods:

1. **CRR tree** — the recursion above, with the holder's exercise region and the
   issuer's cancellation region read off the tree, and Greeks by bumping.
2. **Longstaff–Schwartz Monte Carlo** — the same recursion with the continuation
   value regressed on a basis of polynomials in `S/K`, the two intrinsic kinks,
   and the European value at the remaining maturity. Two details matter: the
   regression is fitted on *all* paths, not only the in-the-money ones, because
   the issuer's decision needs a continuation estimate everywhere; and the
   European basis function is what makes the fit accurate near the strike, where
   the decision is a level comparison against `G + δ`.
3. **Crank–Nicolson finite differences** with two obstacles, projecting the
   solution back into `[G, H]` after each step.
4. **A rigorous bracket**, `G_0 ≤ V ≤ min(American, G_0 + δ)`, which needs no
   simulation at all.

What is *not* implemented: the pathwise dual bounds of Kühn, Kyprianou and van
Schaik. That paper was not available while building this, and the obvious
shortcut does not work — freezing one side's policy and optimising the other
with a regression gives a biased estimate of the sup/inf, and the bias runs the
wrong way on the minimising side, so the result is not a bound. Rather than
present a bound that is not one, the bracket above is used and this gap is
stated.

**Two findings worth stating plainly.** First, for a put struck at spot the
holder's payoff is zero and the issuer's time value is not, so the issuer
cancels immediately and the price is *exactly* the penalty, for every penalty
below about 4.4% of spot; above that the cancellation right is worthless and the
price is the American value. Second, where the penalty cap binds, vega, rho and
theta are all zero — the price is `intrinsic + δ` and stops depending on the
market at all.

## What this is not

No market prices exist for any of this. India has no catastrophe bond market and
nothing like an Israeli option trades on the NIFTY. The Chennai and Bengaluru
contracts were constructed for this exercise and are labelled as such wherever
they appear. Nothing here is a quote, a recommendation, or investment advice.
