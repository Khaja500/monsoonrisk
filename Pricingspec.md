# Technical Specification: MonsoonRisk

Read `plan.md` first for scope, phases and risks. Section numbers here are referenced from there.

## 0. Conventions

- Language: Python 3.11+. Core libraries: numpy, scipy, pandas, xarray, imdlib, matplotlib, pytest. Optional: QuantLib-Python, numba, a web framework for the front end.
- Units: rainfall in mm, money in INR (bond face value normalised to 100), time in years, rates as decimals with continuous compounding unless stated.
- Reproducibility: every stochastic routine takes an explicit `seed`. All raw downloads are cached under `data/raw/` with a provenance note (source, date, version).
- Config-driven: cities, season windows, bond terms and contract parameters live in YAML files, not in code.
- A "TO VERIFY" tag marks an item I could not confirm while writing this spec.

---

# Module A: Rainfall data and risk layer

## A.1 Purpose
Produce, for each city, (1) a clean daily rainfall series, (2) season-level indices, and (3) fitted distributions that Module B can price from. A daily simulator is an optional upgrade.

## A.2 Locations

| City | Approximate coordinates | Role |
|---|---|---|
| Mumbai | 19.1 N, 72.9 E | Matches the traded RAINMUMBAI contract |
| Chennai | 13.1 N, 80.3 E | Constructed analogue; no traded contract |
| Bengaluru | 13.0 N, 77.6 E | Constructed analogue; no traded contract |

Use the nearest 0.25-degree grid cell, and as a sensitivity test the average of the four surrounding cells. Chennai and Bengaluru indices are **constructed analogues of RAINMUMBAI for pricing exercises; no such contracts exist and they must be labelled that way in every output.**

## A.3 Data acquisition
- Source: IMD gridded daily rainfall, 0.25 degree, 1901 to present, via `imdlib` (`get_data`, `open_data`, `get_xarray`, export to CSV or NetCDF).
- Real-time gridded rainfall is available (`get_real_data`, `open_real_data`) but is provisional and may be revised; keep it in a separate table and never mix it silently with the archive.
- Store raw files unchanged. Write processed daily series to `data/processed/{city}_daily.csv` with columns `date, rain_mm, source, is_provisional`.
- TO VERIFY: station-level (Santacruz, Colaba, Chennai, Bengaluru) data access. If found, use it as a cross-check against the grid.

## A.4 Seasons and long-period average

**Config (`cities.yaml`)**

| City | Season window | Basis |
|---|---|---|
| Mumbai | 1 Jun to 30 Sep | RAINMUMBAI is defined over June to September |
| Chennai | 1 Oct to 31 Dec | IMD reports October to December as the chief rainy season for the Tamil Nadu and Puducherry subdivision (about 48% of annual rainfall). A Chennai weather blog citing IMD station normals puts the city's share near 60%. TO VERIFY with the data. |
| Bengaluru | Chosen from data | Evaluate candidate windows (for example Jun to Nov, Sep to Nov); pick the one capturing the largest share of annual rainfall with the fewest months; record the choice and the share |

**Long-period average (LPA)**
- Baseline period 1991 to 2020 (matches RAINMUMBAI's stated 30-year basis).
- `LPA[d]` = mean rainfall over the baseline years for each calendar day `d`, then smoothed (default: centred 15-day moving average; make the window a parameter). Raw daily means are noisy, so smoothing is a design choice.
- TO VERIFY: NCDEX's own method for the daily normal. Compare against the contract specification before relying on exact equivalence.
- Check: Mumbai's seasonal LPA total should be close to the reported 2,206.7 mm. Report the difference; treat it as a measure of grid-versus-station mismatch, not as a failure.

## A.5 Indices
All indices are functions of a daily series for a season window:

| Index | Definition | Used for |
|---|---|---|
| `CDR` (cumulative deviation) | Sum over days of `rain_d - LPA_d`, accumulated through the season | RAINMUMBAI-style futures, coupon-linked bonds |
| `SEAS_TOTAL` | Sum of `rain_d` over the season | Drought-style coupon triggers |
| `MAX1`, `MAX3` | Highest 1-day and 3-day rainfall in the season | Flood-style principal-at-risk triggers |
| `WET_DAYS` | Count of days with `rain_d` above a threshold (default 2.5 mm; make configurable) | Diagnostics |

Output: `data/processed/{city}_season_index.csv`, one row per year, columns `year, CDR, SEAS_TOTAL, MAX1, MAX3, WET_DAYS`.

## A.6 Distribution fitting (version 1: baseline)
For each city and index:
1. Candidate families: normal, skew-normal and gamma for totals and `CDR`; generalised extreme value (GEV) for `MAX1` and `MAX3`.
2. Fit by maximum likelihood; compare by AIC, QQ plots and a Kolmogorov-Smirnov test.
3. Bootstrap (at least 1,000 resamples) for confidence intervals on key quantiles.
4. Check autocorrelation of annual values and cross-city rank correlation (needed for multi-year and multi-city bonds).

Interface: `SeasonDistribution(city, index).cdf(x)`, `.ppf(q)`, `.sample(n, seed)`, plus `burn_sample()` returning the historical values for burn analysis.

## A.7 Daily simulator (version 2: optional)
- **Occurrence:** first-order Markov chain with seasonally varying transition probabilities.
- **Amount on wet days:** gamma or mixed exponential body with a generalised Pareto tail.
- **Season-level factor:** one random multiplier per simulated season (for example lognormal), optionally regressed on ENSO or Indian Ocean Dipole indicators (TO VERIFY data access).
- **Why the factor:** daily-only models have been reported to understate rainfall variability, which would bias every priced product.
- **Fit:** maximum likelihood on the baseline period.
- **Validation:** simulated versus historical seasonal totals (mean, variance, quantiles), dry-spell and wet-spell lengths, frequency of extreme days, and the shape of the `CDR` path. Compare priced results with the version 1 baseline.

## A.8 Public interface
```
RainfallDataset.load(city) -> DataFrame
IndexBuilder(city, season, lpa).build() -> DataFrame
SeasonDistribution(city, index).fit()
DailySimulator(city).fit().simulate(n_seasons, seed) -> array [seasons, days]
```

## A.9 Tests and acceptance
- No missing dates inside seasons; no negative rainfall; provisional data flagged.
- Index builder reproduces hand-computed values on a small synthetic series.
- `CDR` over a season built from exactly the LPA series equals zero.
- Fitted distribution quantiles lie within bootstrap intervals of empirical quantiles for central values.
- Simulator (if built): simulated seasonal mean within 2 standard errors of historical, and variance within an agreed tolerance (record the tolerance used).

## A.10 Limitations to state in the write-up
- Gridded values are interpolated and may smooth extremes; station readings can differ.
- Roughly a century of data, but only about 30 years for the baseline and for any non-stationarity checks.
- Climate trends may make the 1991 to 2020 baseline imperfect for the future.

---

# Module B: Weather bonds and cat bonds

## B.1 Purpose
Price rainfall-linked bonds for Mumbai, Chennai and Bengaluru from Module A distributions, with an explicit and varied treatment of risk premium.

## B.2 Instruments

**B1: Principal-at-risk bond (parametric cat bond)**
- Face value `F = 100`, tenor `T` years (default 1 and 3), annual seasons.
- Trigger index `I_t` per city (default: `MAX3`, a flood proxy; for Chennai also test `CDR`).
- Attachment `A` and exhaustion `E` (config).
- Loss fraction in year `t`: `l_t = min(1, max(0, (I_t - A) / (E - A)))`.
- Outstanding principal: `P_t = max(0, P_{t-1} - F * l_t)`, `P_0 = F`.
- Coupon each year: `(r + s) * P_{t-1}`, where `r` is the collateral yield (risk-free proxy) and `s` the spread paid to the investor. Principal `P_T` is repaid at maturity.
- Variants: occurrence-based (above) and aggregate-based (loss on the sum of annual indices), config-selectable.

**B2: Weather-linked coupon bond (drought-style)**
- Principal protected. Coupon in year `t`: `c_fixed + kappa * min(cap, max(0, K - I_t)) / scale`, where `I_t` is `SEAS_TOTAL` or `CDR` (config).
- Pays more in dry years; reverse the sign for a wet-year hedge.

**B3 (optional): Index future (Mumbai only, sanity check)**
- Fair value of a `CDR`-style future: `multiplier * E^Q[CDR_T | information at t]`, with `multiplier = Rs 50 per mm`.
- Chennai and Bengaluru analogues are hypothetical.

## B.3 Pricing measure and risk premium

The rainfall index is not tradeable, so the market is incomplete and no single hedge-based price exists. The literature on weather derivatives lists actuarial, equilibrium and indifference-pricing approaches. This project makes the risk adjustment explicit with three rules, each reported side by side:

| Rule | Definition | Parameter |
|---|---|---|
| R1: expected-loss multiple | `s* = m * EL_annual` | `m` (try 1, 1.5, 2, 3) |
| R2: Wang transform | Distort the loss exceedance probability: `S^Q(x) = Phi(Phi^{-1}(S(x)) + lambda)`; solve for `s*` so that the price equals par under `Q` | `lambda` |
| R3: standard-deviation loading | `s* = EL_annual + beta * SD_annual` | `beta` |

R2 is a standard technique in insurance-linked securities; confirm the exact form against a literature source before final use (TO VERIFY). There are no Indian cat bond prices to calibrate the parameters against (India has not issued one), so default parameter values are placeholders and results are reported as sensitivities.

## B.4 Inputs

| Input | Source |
|---|---|
| Index distribution or burn sample | Module A |
| Terms: `A`, `E`, `T`, coupon rule, trigger index | `bonds.yaml` |
| Discount curve | Flat rate from the 91-day T-bill (RBI auction yield); optional term curve |
| Risk-premium parameters `m`, `lambda`, `beta` | Config |
| Multi-year dependence | Independent seasons by default; optional rank correlation from Module A |

## B.5 Outputs
For each city, bond type and risk rule:
- Price per 100 face and fair spread `s*`.
- Annual and total expected loss (EL), standard deviation of loss.
- Probability of attachment `P(I > A)` and of exhaustion `P(I >= E)`.
- Loss distribution, loss-exceedance curve, investor VaR and CVaR at 95% and 99%.
- Sensitivity tables to `A`, `E`, tenor and risk-rule parameters.
- Cross-city comparison and, if built, a multi-city basket bond (pays on the worst or average city index) using a Gaussian copula fitted to annual indices.

## B.6 Methods
1. **Burn analysis:** apply the payoff to each historical year; average. Baseline.
2. **Analytic from fitted distribution:** numerical integration of expected loss over the fitted density.
3. **Monte Carlo:** sample from fitted distributions (version 1) or the daily simulator (version 2); use antithetic sampling and report standard errors.

## B.7 Validation
- Cross-check B1 expected loss and price against the QuantLib cat bond engine if it is exposed in QuantLib-Python (TO VERIFY; the C++ library has a cat bond module). Otherwise validate against an independent closed-form calculation in a notebook.
- Compare burn analysis, analytic and Monte Carlo prices; they should agree within sampling error.
- For Mumbai, compare B3 with any available RAINMUMBAI price (TO VERIFY availability).

## B.8 Public interface
```
ParametricBond(city, index, attach, exhaust, tenor, coupon_rule, aggregate=False)
WeatherCouponBond(city, index, k, cap, kappa, c_fixed, tenor)
PremiumRule.r1(m) / .wang(lam) / .sd_load(beta)
price(bond, distribution_or_sample, premium_rule, discount) -> PricingResult
```

## B.9 Tests and acceptance
- If `A = E`, the bond is a binary trigger; EL equals the trigger probability times face.
- At the fair spread `s*`, the present value of expected cash flows under the pricing measure equals par within tolerance. For a fixed spread, price decreases as expected loss increases.
- Raising `A` (with `E` fixed) lowers EL and probability of attachment.
- `E[l_t]` computed by integration equals the Monte Carlo mean within three standard errors.
- With zero risk premium, the fair spread is zero under R1 and the present value of expected cash flows equals par less the present value of expected principal losses (up to timing conventions).
- Principal never goes negative; coupon never exceeds `(r + s) * F`.

## B.10 Limitations to state
- Model-based pricing; no market prices to calibrate.
- Chennai and Bengaluru products are constructed analogues of an existing Mumbai contract, not traded instruments.
- Annual-season independence is an assumption; check autocorrelation and climate-state effects.
- Grid data may differ from the stations a real contract would settle on.

---

# Module C: Israeli (game) option on NIFTY 50

## C.1 Purpose
Price a game option: an American-style option whose issuer may also cancel it early by paying a penalty. Its fair price is the value of a Dynkin game. This module is independent of A and B.

## C.2 Contract definition
- Underlying: NIFTY 50 index level `S_t`.
- Holder may exercise at any time up to maturity `T` for payoff `G_t`: put `max(K - S_t, 0)` or call `max(S_t - K, 0)`.
- Issuer may cancel at any time, paying `H_t = G_t + delta`, with penalty `delta >= 0` (default: a percentage of `S_0`, tested at 0%, 1%, 2%, 5%).
- The product is hypothetical; there is no market for it.

## C.3 Discrete-time recursion
On a time grid `t_0..t_N`, with `C_i` the discounted conditional expectation of `V_{i+1}` under the risk-neutral measure:

```
V_N = G_N
V_i = min( H_i , max( G_i , C_i ) )
```

The holder maximises over exercising, the issuer minimises over cancelling. Validate this recursion against Kifer's binomial results (TO VERIFY by reading the paper) before building on it.

## C.4 Underlying dynamics and inputs

**Model 1 (baseline):** geometric Brownian motion with continuous dividend yield `q` and risk-free rate `r`.

| Input | Source and method |
|---|---|
| `S_0`, `K`, `T` | Latest NIFTY 50 close; strikes at 95%, 100%, 105% of `S_0`; tenors 3 months to 2 years |
| Volatility `sigma` | Realised volatility from index returns (1-year and 3-year windows) and the India VIX level as an implied-volatility proxy for about 30 days. Report prices under both and under a grid of values |
| Dividend yield `q` | Estimate from the gap between price-return and total-return growth over a window: `q ~ ln(TRI growth) - ln(price growth)` annualised. A recent factsheet figure of about 1.35% (29 May 2026) is a sanity check, not an input |
| Risk-free `r` | RBI 91-day T-bill auction yield (about 5.25% in early July 2026; policy rate 5.25% at end of July 2026) or a longer tenor matched to `T`. Update at run time |
| Penalty `delta` | Config |

**Model 2 (stretch):** Heston or local volatility calibrated to NIFTY option prices. TO VERIFY free access to historical NSE option-chain data; if not available, calibrate to India VIX levels only or skip.

**Data sources**
- NIFTY 50 price and total-return history, PE, PB, dividend yield: NSE Indices (niftyindices.com). A third-party spreadsheet that downloaded these (last updated October 2023) exists; current status unknown, so prefer direct downloads. TO VERIFY bulk historical download on NSE.
- India VIX history: NSE.
- T-bill yields: RBI auction results or FBIL data.

## C.5 Methods
1. **M1: Binomial (CRR) solver.** Apply the C.3 recursion on a tree with `N` up to about 5,000 steps. Extract the holder's exercise boundary and the issuer's cancellation boundary. Convergence study in `N`.
2. **M2: Longstaff-Schwartz Monte Carlo.** Regress continuation values on basis functions of `S_t` (polynomials of degree 3 to 5 as default), then apply `min(H, max(G, C_hat))` at each date. Implement the recent two-step approach from arXiv 2401.08093 after reading the paper (TO VERIFY details); use the baseline regression recursion until then.
3. **M3: Pathwise dual bounds** (Kühn, Kyprianou and van Schaik). Produce an upper and lower bound bracketing the price, with a confidence interval.
4. **M4 (stretch): Finite difference** with two free boundaries (double-obstacle problem).

## C.6 Validation
- **No cancellation limit:** as `delta` grows (or `H` set very high), `V` converges to the American option price from a standard American binomial solver.
- **Zero penalty:** with `delta = 0`, `V_i = G_i` at all nodes (the issuer can cancel at once by paying intrinsic value).
- **Bounds:** `G_i <= V_i <= min(H_i, American value)` at every node.
- **Monotonicity:** `V` is non-decreasing in `delta`.
- **Cross-method agreement:** binomial value lies inside the Monte Carlo confidence interval and inside the dual bounds.
- **Explicit benchmark:** Kyprianou (2004) gives explicit solutions for two perpetual Israeli options; compare against them with a long maturity (TO VERIFY formulas from the paper).
- **Convergence plots:** price versus `N` (tree) and versus number of paths (Monte Carlo), with standard errors.

## C.7 Outputs
- Price `V_0` with standard error (Monte Carlo) or tree convergence estimate.
- Exercise boundary `S*_holder(t)` and cancellation boundary `S*_issuer(t)`.
- Greeks (delta, gamma, vega, rho) from tree differences or common-random-number bumps.
- Decomposition: American value minus game value equals the value of the issuer's cancellation right.
- Price tables over strike, tenor, volatility and penalty; plots for the report.

## C.8 Public interface
```
GameOption(kind, strike, maturity, penalty)
BinomialSolver(model, n_steps).price(option) -> GameResult
LSMSolver(model, n_paths, basis, seed).price(option) -> GameResult
DualBounds(model, n_paths, seed).bounds(option) -> (lower, upper)
NiftyInputs.from_data(...) -> model parameters (S0, sigma, q, r)
```

## C.9 Tests and acceptance
All checks in C.6 are automated tests, with explicit numeric tolerances recorded in the test file. Add a regression test that fixes seeds and inputs and checks stored reference prices.

## C.10 Limitations to state
- Hypothetical contract; no market price exists to calibrate or compare against.
- Constant-volatility baseline ignores the volatility smile and skew.
- NIFTY 50 is an index; exposure in practice goes through futures or ETFs, so carry and tracking issues are ignored.
- Continuous dividend yield is an approximation to discrete dividend payments.

---

# Cross-cutting

## X.1 Data source register

| Source | Use | Status in this session |
|---|---|---|
| IMD gridded rainfall (0.25 degree, 1901 to present) via `imdlib` | Module A | Verified: package exists, downloads, reads to xarray, exports CSV/NetCDF |
| IMD real-time gridded rainfall | Current-season updates | Verified, but provisional and subject to revision |
| IMD station data (Santacruz, Colaba, Chennai, Bengaluru) | Cross-check | Not verified |
| ENSO / Indian Ocean Dipole indices | Optional season-level factor | Not checked |
| NSE Indices: NIFTY 50 price, TRI, dividend yield, India VIX | Module C | Existence of the data confirmed via factsheets and a third-party tool; direct bulk download not verified |
| RBI T-bill auction yields / FBIL | Risk-free rate | Verified that yields are published; programmatic download not tested |
| NSE option-chain history | Heston extension | Not verified |
| RAINMUMBAI price history | Module B sanity check | Not verified |

## X.2 Assumption log
Maintain `docs/assumptions.md` listing every modelling choice (smoothing window, wet-day threshold, risk-premium defaults, tolerance values) with the date and reason. Update it whenever a default changes.

## X.3 Testing strategy
- Unit tests per function, property tests for monotonicity and bounds, regression tests with fixed seeds.
- Every figure in the write-up is generated by a script, not edited by hand.
- A single `make all` (or equivalent) command regenerates data tables, runs tests, and produces figures.

## X.4 Optional front end
- Module B page: choose city, trigger index, attachment, exhaustion, tenor and risk rule; show price, fair spread, expected loss and the loss-exceedance curve.
- Module C page: choose strike, tenor, penalty and method; show price, boundaries and convergence.
- Label the Chennai and Bengaluru pages as constructed analogues and all Module C results as hypothetical.

## X.5 Deliverables
- Source code and tests.
- Processed data tables and figures.
- Methodology write-up (`docs/`), covering assumptions, validation results and limitations.
- `README.md` with setup and run instructions.
