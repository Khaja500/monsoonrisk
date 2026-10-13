# Technical Specification: MonsoonRisk

Read `Pricingplan.md` first for scope, status and findings. This document describes
the system **as built**; where something in the original specification was not built,
or was built differently, that is stated in place rather than quietly dropped.

Last revised 13 October 2026.

## 0. Conventions

- Language: Python 3.11+. Core libraries: numpy, scipy, pandas, imdlib, PyYAML, pytest. The front end is plain ES modules with no dependencies and no build step.
- Units: rainfall in mm, money in INR (bond face value normalised to 100), time in years, rates as decimals with continuous compounding unless stated.
- Reproducibility: every stochastic routine takes an explicit `seed`. Raw downloads are cached under `data/raw/` with provenance in `data/raw/README.md`.
- Config-driven: cities, season windows, bond terms, contract parameters and published forecast inputs live in `config/*.yaml`, not in code.
- Environment overrides used by the scheduled job: `MONSOONRISK_ASOF`, `MONSOONRISK_NBOOT`, `MONSOONRISK_REFRESH`.
- **"NOT BUILT"** marks something in the original specification that does not exist. **"CHANGED"** marks something built differently from the original, with the reason.

---

# Module A: Rainfall data and risk layer

## A.1 Purpose
Produce, per city, (1) a clean daily rainfall series, (2) season-level indices, (3) fitted distributions and an independent tail estimate, and (4) the climate state that the seasonal forecast in Module B regresses on.

## A.2 Locations

| City | Grid cell used | Role |
|---|---|---|
| Mumbai | 19.00 N, 73.00 E | Matches the traded RAINMUMBAI contract |
| Chennai | 13.25 N, 80.25 E | Constructed analogue; no traded contract |
| Bengaluru | 13.00 N, 77.50 E | Constructed analogue; no traded contract |

`choose_cell` takes the nearest 0.25° cell with complete land data in a probe year, searching outward through the surrounding block; the cells above are what that returns, and they are published on the site. Chennai and Bengaluru indices are **constructed analogues of RAINMUMBAI for pricing exercises; no such contracts exist and they are labelled that way in every output.**

## A.3 Data acquisition
- Archive: IMD gridded daily rainfall, 0.25°, via `imdlib` (`get_data`, `open_data`, `get_xarray`), 1981–2025. One file per year, ~25 MB; `scripts/download_imd.py` fetches them in parallel processes.
- **CHANGED — the current season.** The original plan was to use IMD's real-time gridded feed. That server timed out on 13 October 2026, so the 2026 days come from NASA POWER's corrected precipitation (`PRECTOTCORR`, MERRA-2). `build_city_series` still tries IMD real-time first when `allow_realtime` is set and prefers the archive whenever it exists, so the fallback unwinds itself the moment IMD publishes.
- Every row carries `source_group` ∈ {`imd_grid`, `imd_rt`, `nasa_power`}, a human-readable `source`, and `is_provisional`. Sources are never mixed silently.
- Processed series are cached to `data/processed/{city}_daily.csv`; extracting one cell means opening 45 yearly grids, so everything downstream reads the cache.
- **Not available.** Station-level data (Santacruz, Colaba, Nungambakkam) was not found in machine-readable form. Published seasonal totals from IMD-sourced reports are used for the 2026 actuals and as the settlement normals.

## A.4 Seasons, normals and the bias correction

**Config (`cities.yaml`)**

| City | Season window | Basis |
|---|---|---|
| Mumbai | 1 Jun – 30 Sep | RAINMUMBAI is defined over June–September |
| Chennai | 1 Oct – 31 Dec | IMD's north-east monsoon, the chief rainy season for Tamil Nadu and Puducherry (~48% of annual rainfall) |
| Bengaluru | 1 Jun – 30 Nov | **Selected from data**: the fewest months capturing ≥75% of annual rainfall. Result: 6 months, 78.7% |

**Long-period average.** Baseline 1991–2020, matching RAINMUMBAI's stated basis. `LPA[d]` is the mean rainfall for calendar day `d` over the baseline, smoothed with a centred 15-day moving average (window is a config knob).

**Anchor consistency.** After smoothing, the normal is rescaled over the season days so it sums exactly to the contract anchor. This makes the exchange's identity exact: `anchor + CDR = SEAS_TOTAL`, so the end-of-season spot is the realised seasonal rainfall. Without it, smoothing leaks ≈3.6 mm across the season boundary — ₹180 per lot of silent error.

**Bias correction (`source_bias_factors`).** A 0.25° cell is not a station, and a reanalysis is not the grid. Each source is scaled so that *its own* 1991–2020 seasonal normal equals the published station normal:

| City | Grid seasonal normal | Station normal | Grid factor |
|---|---|---|---|
| Mumbai | 2,723.5 mm | 2,206.7 mm | ×0.810 |
| Chennai | 743.4 mm | 750.0 mm | ×1.009 |
| Bengaluru | 662.3 mm | none verified | ×1.000 |

NASA POWER gets its own factor from its own climatology; IMD real-time inherits the archive's, because the real-time product is too short for a 30-year normal. **This fixes the level, not the shape of the distribution** — stated wherever tail numbers are published.

## A.5 Indices

| Index | Definition | Used for |
|---|---|---|
| `CDR` | Σ (`rain_d` − `LPA_d`) over the season | the index future |
| `SEAS_TOTAL` | Σ `rain_d` over the season | drought triggers, the seasonal forecast |
| `MAX1`, `MAX3` | highest 1-day and 3-day rainfall in the season | flood triggers |
| `WET_DAYS` | days above 2.5 mm | diagnostics |

Each row also carries `days_observed`, `days_expected`, `complete` and `provisional`. Fitting uses complete, non-provisional seasons only.

## A.6 Distribution fitting
1. Candidates: normal, skew-normal, gamma and logistic for totals and `CDR`; GEV, gamma and lognormal for `MAX1` and `MAX3`.
2. Maximum likelihood, ranked by AIC, with a Kolmogorov–Smirnov statistic reported.
3. Percentile bootstrap (2,000 resamples) of the empirical quantiles.
4. Lag-1 autocorrelation per city and cross-city Spearman rank correlation, both exported, because multi-year and multi-city products assume things about them.

Interface: `SeasonDistribution(city, index)` with `.cdf`, `.ppf`, `.sample_draws(n, seed)` and `.burn_sample()`.

## A.6b Tail cross-check: peaks over threshold (**new**)
`peaks_over_threshold(daily, window, threshold_q, run_days, horizon_days)` fits a generalised Pareto distribution to declustered exceedances of a high threshold of the rolling `horizon_days` total, and converts the fit back to return levels for the seasonal maximum through the exceedance rate.

Why it exists: an annual-maxima fit uses one observation per season and throws away every other large event, which is expensive with 45 seasons. Three thresholds (90th, 95th, 97.5th percentile of season days) are exported so threshold stability — the standard POT diagnostic — is visible. Results at the 95th percentile:

| City | 1-in-100 `MAX3`, annual-maxima fit | 1-in-100, POT | ξ |
|---|---|---|---|
| Mumbai | 562.7 mm | 516.4 mm | −0.85 |
| Chennai | 675.3 mm | 653.3 mm | −0.21 |
| Bengaluru | 336.3 mm | 344.6 mm | +0.01 |

Chennai and Bengaluru agree within about 3%. Mumbai does not: the POT shape parameter is strongly negative, implying a bounded tail, and it sits exactly where the flood bond's exhaustion point is. That disagreement is reported, not averaged away.

## A.7 Daily simulator — **NOT BUILT**
Specified originally as a Markov occurrence chain with a gamma/GPD amount model and a season-level factor. Not built: the baseline distribution layer plus the POT cross-check covers what Module B needs, and the simulator earns its place only when something path-dependent is priced. It is the first item in the backlog.

## A.8 Climate predictors (**new**, `src/a_rainfall/climate.py`)
Monthly Niño 3.4 (NOAA PSL) and the HadISST Dipole Mode Index (NOAA PSL), parsed from their fixed-width text form and cached under `data/raw/climate/`.

`season_state(year, season_start_month, indices, window=3)` returns the mean of each index over the three months ending the month *before* the season opens — so for a June season, the March–May mean, which is public by 1 June — together with a list of which predictors were actually available.

Publication lag is handled explicitly rather than filled in: Niño 3.4 runs to the previous month and is always available at a season start; the Dipole Mode Index lags several months, so it is usable in a backtest and typically **not** for a season starting now. For the Chennai October 2026 season, `available = ['nino34']`.

## A.9 Public interface
```
build_city_series(city, current_year, allow_realtime=False, rebuild=False) -> DataFrame
load_cached_series(city)                 -> (DataFrame, Series)
build_city_index(city, frame, power_ref) -> CityIndex
fit_city(city, table)                    -> {index: SeasonDistribution}
peaks_over_threshold(daily, window, ...) -> dict | None
climate.load_all() / climate.season_state(...) / climate.state_table(...)
```

## A.10 Tests and acceptance (`tests/test_a_rainfall.py`)
- No negative rainfall; provisional rows flagged; season-day counts correct.
- The index builder reproduces hand-computed `MAX1`, `MAX3`, `WET_DAYS` and `SEAS_TOTAL` on a synthetic series.
- `CDR` over a season built from exactly the LPA is zero.
- The daily normal of a constant series is that constant.
- Window selection prefers the fewest months above the share threshold.
- POT return levels increase with return period, and POT declines to fit (returns `None`) rather than crashing when a series has no exceedances.

## A.11 Limitations stated in output
- Grid values are interpolated and smooth extremes; the bias correction fixes the mean only.
- 45 seasons, of which 30 define the baseline; tail quantiles are correspondingly uncertain.
- The 1991–2020 baseline may not describe the future climate.

---

# Module B: The index future, weather bonds and cat bonds

## B.1 Purpose
Price the rainfall index future and rainfall-linked bonds from Module A, with the risk premium made explicit and the parameter uncertainty made visible.

## B.2 Instruments

**B1: Principal-at-risk bond.** Face 100, tenor 1 or 3 years. Loss fraction per season `l_t = clip((I_t − A)/(E − A), 0, 1)`, inverted for drought triggers (`A > E`, loss grows as the index falls). Principal `P_t = max(0, P_{t−1} − 100·l_t)` with losses capped at the principal outstanding; coupon `(r + s)·P_{t−1}`; redemption `P_T`. Occurrence and aggregate variants. `A = E` is permitted and degenerates to a binary trigger.

**B2: Weather-linked coupon bond.** Principal protected. Coupon `c_fixed + κ·min(cap, max(0, K − I_t))/scale`, paying more in a dry season.

**B3: The index future.** The contract that matters, because it is the one with a real settlement to check against. See B.6.

## B.3 Pricing measure and risk premium
The rainfall index is not tradeable, the market is incomplete, and India has issued no catastrophe bond, so there is nothing to calibrate to. Three rules are implemented and always reported together:

| Rule | Definition | Parameter grid |
|---|---|---|
| R1 expected-loss multiple | `s* = m · EL` | m ∈ {1, 1.5, 2, 3} |
| R2 Wang transform | `S_Q(x) = Φ(Φ⁻¹(S_P(x)) + λ)`; `s*` solves price = par under Q | λ ∈ {0, 0.15, 0.25, 0.4} |
| R3 standard-deviation loading | `s* = EL + β·SD` | β ∈ {0, 0.25, 0.5, 1} |

The Wang implementation produces **weights on whole simulated paths**, ranked by total discounted loss, so outstanding principal, coupons and redemption are all averaged under one measure. The par condition then solves linearly:

```
s* = ( 100 − df_T·E_Q[P_T] − r·Σ df_t·E_Q[P_{t−1}] ) / Σ df_t·E_Q[P_{t−1}]
```

Default: Wang at λ = 0.25, which implies about 1.7× expected loss.

## B.4 Inputs

| Input | Source |
|---|---|
| Index distribution or burn sample | Module A |
| Terms `A`, `E`, `T`, coupon rule, trigger | `bonds.yaml`; attachment/exhaustion default to the 90th/99th percentile (flood) and 10th/1st (drought) |
| Discount and collateral rate | 5.60% — RBI repo 5.50% (7 Oct 2026) + 10 bp as a 91-day T-bill proxy; the auction yield itself was not retrieved |
| Risk-premium parameters | `bonds.yaml` |
| Seasonal forecast | B.7 |
| Published 2026 weather reports | `forecasts.yaml`, each entry with its source |

## B.5 Outputs
Per city, bond and rule: price per 100 and fair spread; annual and total expected loss; probability of attachment and exhaustion; investor VaR and CVaR at 95% and 99%; a loss-exceedance curve; attachment sensitivity; **and a parameter-uncertainty band** (B.8).

## B.6 The index future
NCDEX publishes an anchored cumulative-deviation spot, `spot_T = anchor + Σ_{d≤T}(rain_d − LPA_d)`, and the contract for a month settles on that spot just after month end. Fair value at a valuation date:

```
F = spot(t) + (factor − 1)·LPA(t, T] + λ·σ(t, T]
```

`σ(t, T]` is the standard deviation of the deviation still to accumulate, measured over the same calendar stretch in every historical season. **With `factor = 1` and `λ = 0`, fair value equals the spot** — the future is a martingale under climatology, so every departure from spot must be argued for. `λ` defaults to 0 and is a control on the site rather than a hidden constant.

**CHANGED.** The original specification had a Theil–Sen trend term added directly to the fair value, gated on a Mann–Kendall test. That has been removed: a trend is a forecast, so it now lives inside the forecast model (B.7) where it is selected and scored out of sample like every other variant.

**Backtest.** `backtest(ci, 1991, 2025, walk_forward_rows=...)` marks the model the day before each season opens and compares with the realised settlement. Climatology quotes the anchor; the forecast model uses the walk-forward factor. Reported: bias, MAE, RMSE, worst error, how often the forecast beats climatology, how often they are identical, and the mean absolute P&L per lot.

## B.7 The seasonal forecast (**new**, `src/b_bonds/forecast.py`)
A regression of the seasonal total, as a ratio to the long-period average, on climate state known before the season opens. Five variants:

```
climatology   (the training mean - the thing to beat)
trend         year
enso          nino34
enso_iod      nino34, dmi
enso_trend    nino34, year
```

**Scoring** is a strict expanding window: the model for season `y` is fitted on seasons before `y` only, and all variants are compared on the same scored seasons. A variant is selected only if its out-of-sample RMSE is strictly lower than climatology's; ties and anything worse fall back to climatology.

**`walk_forward`** goes further and re-selects the variant each year from prior data alone, so neither the coefficients nor the choice of model has seen the season being priced. This is what feeds the backtest.

**`factor(state, year)`** returns the predicted ratio, and falls back to climatology with a stated reason when a predictor has not been published yet.

Results are in `Pricingplan.md` §6: skill is small for Mumbai and Bengaluru and absent for Chennai, which is the honest answer and is published as such.

## B.8 Parameter uncertainty (**new**)
`price_with_parameter_uncertainty` resamples the observed seasons with replacement, refits the same distribution family, and re-prices — 200 resamples by default. It returns 5th/50th/95th percentile bands for expected loss, fair spread, attachment and exhaustion probability, and a banded loss-exceedance curve.

This exists because a single curve fitted to 45 observations, with an exhaustion point near the 99th percentile, looks far more precise than the record supports. On the default Mumbai flood bond: expected loss 4.25% point estimate, **1.50%–7.24%** band; fair spread 7.07%, band 2.82%–11.31%.

## B.9 Methods
1. **Burn** — apply the payoff to each observed season; i.i.d. resampling of seasons for multi-year tenors.
2. **Quadrature** — `∫ l(x)·f(x) dx` against the fitted density.
3. **Monte Carlo** — antithetic inverse-transform sampling, with standard errors.

All three run on every bond and are published side by side. On the default Mumbai flood bond they give 4.03% / 4.11% / 4.12% expected loss.

The browser re-implements the same engine (`docs/pricing.js`) by inverse-transform sampling off a 251-point quantile grid, so every control re-prices rather than reading a precomputed cell.

## B.10 Tests and acceptance (`tests/test_b_bonds.py`, `tests/test_b_futures.py`)
Bonds:
- `A = E` is a binary trigger and expected loss equals the trigger probability.
- Raising attachment lowers expected loss and attachment probability.
- Quadrature matches Monte Carlo within three standard errors.
- At the fair spread under Wang, the price is par.
- Zero premium gives a zero spread under R1; spread rises with expected loss.
- Principal never goes negative; coupon never exceeds `(r + s)·100`.
- Inverted triggers pay on dry seasons; Wang weights are a probability measure and shift mass to the tail; λ = 0 recovers the physical mean exactly.
- The uncertainty band brackets the point estimate and the banded exceedance curve is monotone.

Future and forecast:
- The exchange identity `anchor + CDR = SEAS_TOTAL` holds.
- Climatology makes the future a martingale at every valuation date.
- A forecast factor moves the price by exactly `(factor − 1)·LPA_remaining`; the risk premium by exactly `λ·σ_remaining`.
- Expiry is the last day of the contract month, leap years included.
- Season-start marking prices every contract month identically.
- The forecast recovers a planted signal (`ratio = 1 + 0.2·nino34`) and selects an ENSO variant; on pure noise it selects climatology; an unpublished predictor falls back with a reason.
- **No look-ahead**: corrupting every season from 2015 on leaves every walk-forward factor before 2015 bit-identical.

## B.11 Limitations stated in output
- Model-based pricing; no market to calibrate.
- Chennai and Bengaluru products are constructed analogues, not traded instruments.
- Annual seasons are assumed independent; the autocorrelation and cross-city correlations are published so the assumption can be checked.
- Grid data differs from the stations a real contract settles on.

---

# Module C: Israeli (game) option on NIFTY 50

## C.1 Purpose
Price a game option: an American-style option whose issuer may also cancel early by paying a penalty. Its fair price is the value of a Dynkin game. Independent of A and B.

## C.2 Contract
- Underlying: NIFTY 50 level `S_t`. Holder exercises at any time for `G_t`; issuer cancels at any time for `H_t = G_t + δ`, `δ ≥ 0`.
- Ties go to the holder, the usual convention.
- Strikes at 95/100/105% of spot; tenors 3 months to 2 years; δ tested from 0 to 10% of spot.
- The product is hypothetical; nothing like it trades on the NIFTY.

## C.3 Discrete recursion
```
V_N = G_N
V_i = min( H_i , max( G_i , C_i ) )
```
`C_i` is the discounted risk-neutral continuation value. One code path serves all three styles — `game` applies the min-max, `american` drops the min, `european` drops both — so the American value and the value of the cancellation right come from the same recursion.

## C.4 Dynamics and inputs
Geometric Brownian motion with continuous dividend yield. Inputs are dated and sourced in `config/game_option.yaml`:

| Input | Value | Source |
|---|---|---|
| `S_0` | 22,721.95 | NIFTY 50 close, 13 Oct 2026 |
| `σ` | 15.16% | India VIX, 12 Oct 2026 |
| `r` | 5.60% | RBI repo 5.50% (7 Oct 2026) + 10 bp |
| `q` | 1.23% | NSE Indices dividend yield, 1 Oct 2026 |
| realised vol | **not computed** | Yahoo HTTP 429, NSE 503, niftyindices 302 on 13 Oct 2026 |

`nifty.py` computes realised volatility automatically if a `date,close` CSV is placed at `data/raw/nifty50_close.csv`. Until then India VIX is the volatility input and a volatility grid is published alongside every price.

**Heston / local volatility — NOT BUILT.** No free NSE option-chain history was obtainable, so any such model would carry a free parameter dressed as a calibration.

## C.5 Methods
1. **M1 CRR tree** (`binomial.py`). Up to ~3,000 steps. Extracts the holder's exercise boundary and the issuer's cancellation region; Greeks by bumping. Broadie–Detemple terminal smoothing is applied for the American and game styles and deliberately skipped for European, so the comparison against the closed form stays an honest test of the lattice.
2. **M2 Longstaff–Schwartz** (`lsm.py`). Basis: polynomials in `S/K`, the two intrinsic kinks, and the European value at the remaining maturity. Two details are load-bearing: the regression is fitted on **all** paths, not only in-the-money ones, because the issuer's decision needs a continuation estimate everywhere; and the European basis function is what makes the fit accurate near the strike, where the decision is a level comparison against `G + δ`. Compared against the tree **at a matched monitoring frequency**, because the number of decision dates is part of the contract.
3. **M3 Rigorous bracket** (`dual.py`). `G_0 ≤ V ≤ min(American, G_0 + δ)`, requiring no simulation, plus a policy simulation that replays the tree's stopping rules on independent paths. **CHANGED from the original specification**, which asked for the pathwise dual bounds of Kühn, Kyprianou and van Schaik. That paper was unavailable, and the obvious shortcut — freeze one side's policy and optimise the other by regression — gives a biased estimate whose bias runs the wrong way on the minimising side, so it is not a bound; measured, it produced "lower bounds" above the tree price. The module says so in its own docstring rather than presenting a bound that is not one.
4. **M4 Crank–Nicolson finite differences** (`fd.py`) with two obstacles, projecting the solution into `[G, H]` after each step. Listed as a stretch in the original plan; built, and it is the main independent check on the tree. The European case matches Black–Scholes to 4×10⁻⁵ relative.
5. **Averaged lattice** (`averaged_price`, **new**). A double-obstacle lattice oscillates in the step count because the free boundary sits between nodes differently at every resolution. The price is averaged over a band of step counts and the standard deviation across that band is published as the numerical uncertainty that remains. On the worst contract priced here, single trees range 152.9–157.3 while the average is 154.6 ± 1.3.

## C.6 Validation (`tests/test_c_game.py`, and re-run at build time)
| Check | Result |
|---|---|
| European tree vs Black–Scholes | 1417.609 vs 1417.610 |
| δ = 0 ⇒ `V = G_0` (issuer cancels at once) | exact to 1e-6 |
| δ → ∞ ⇒ American | exact to 1e-12 |
| `V` non-decreasing in δ | holds across the grid |
| `G_0 ≤ V ≤ min(American, G_0 + δ)` | holds at five strike/penalty combinations |
| Monte Carlo vs tree at matched frequency | worst gap 3.55% |
| Finite differences vs averaged tree | worst gap ~3.5% |
| Lattice oscillation measured, not hidden | 2σ swing across step counts published per contract |
| Terminal smoothing changes the answer | by under 0.01 points — recorded as a negative result, because it locates the oscillation in the free boundary rather than the payoff kink |

The worst case in every row is the same contract: an out-of-the-money put at δ = 1%, whose free boundary sits on the payoff kink. It is published rather than excluded.

**Not done:** comparison against Kyprianou's explicit perpetual solutions, which needs the paper.

## C.7 Outputs
Price with numerical uncertainty; American, European and the cancellation right; exercise boundary and cancellation locus; Greeks (delta, gamma, vega, rho, theta); price tables over strike, tenor and penalty; a volatility grid; a penalty curve for both an at-the-money and an in-the-money contract; and a convergence study.

## C.8 Public interface
```
price_tree(s0, strike, r, q, sigma, maturity, steps, kind, penalty, style, collect, smooth)
price_game(...)                 -> GameResult with boundaries, Greeks, bound checks
averaged_price(..., steps_list) -> {price, sd, min, max, values}
price_lsm(...)                  -> LSMResult with a standard error
price_fd(..., style)            -> Crank-Nicolson with two obstacles
bounds(...)                     -> rigorous bracket + policy simulation
nifty.load_inputs()             -> dated market inputs
```

## C.9 Structural results worth stating
- For a put struck at spot the price is **exactly** δ until δ reaches 4.44% of spot, above which the cancellation right is worthless and the price is the American value. The holder's payoff is zero and the issuer's time value is not, so the issuer cancels at once.
- Where that cap binds, vega, rho and theta are all zero: the price is `intrinsic + δ` and has stopped depending on the market.
- The issuer's cancellation region collapses onto the strike: once the cap binds on a region the value there is `G + δ`, linear away from the kink, so continuation is linear too and the strict inequality survives only at the kink.

## C.10 Limitations stated in output
- Hypothetical contract; no market price to calibrate or compare against.
- Constant volatility: no smile, no skew.
- NIFTY 50 is an index; real exposure goes through futures or ETFs, so carry and tracking are ignored.
- Continuous dividend yield approximates discrete dividends.

---

# Cross-cutting

## X.1 Data source register

| Source | Use | Status |
|---|---|---|
| IMD gridded rainfall 0.25° via `imdlib` | Module A archive 1981–2025 | **Used.** 7 of 45 years needed a retry at lower parallelism |
| IMD real-time gridded rainfall | current season | **Failed** — `imdpune.gov.in` timed out, 13 Oct 2026 |
| NASA POWER `PRECTOTCORR` | current season stand-in and its own bias calibration | **Used**, flagged provisional |
| NOAA PSL Niño 3.4 | forecast predictor | **Used.** Current to the previous month; +2.09 °C in Sep 2026 |
| NOAA PSL Dipole Mode Index (HadISST) | forecast predictor | **Used in backtest.** Lags several months; unavailable for the Chennai 2026 season |
| IMD station data (Colaba, Santacruz, Nungambakkam) | settlement basis, 2026 actuals | **Not machine-readable.** Published totals taken from IMD-sourced reports |
| NCDEX RAINMUMBAI product note and spot methodology | contract terms, the 2,206.7 mm anchor | **Used** |
| IMD north-east monsoon outlook, 1 Oct 2026 | Chennai/Bengaluru forecast band | **Used** |
| NSE Indices: NIFTY 50 history | realised volatility | **Failed** — HTTP 429 / 503 / 302 |
| NSE option-chain history | Heston extension | **Not found free** |
| RAINMUMBAI daily quote history | Module B sanity check | **Not published retrievably** — comparison is against the realised settlement |

## X.2 Assumption log
`docs/notes/assumptions.md` lists every modelling choice with its date and reason: baseline period, smoothing window, anchor rescaling, bias factors, wet-day threshold, season window selection, forecast variants and the selection rule, attachment quantiles, the default premium rule, discount rate, independence assumptions, path counts, tree steps, and the matched-monitoring-frequency comparison rule.

## X.3 Testing strategy
45 tests across four files: unit tests per function, property tests for monotonicity and bounds, limiting-case tests for Module C, a no-look-ahead test for the forecast backtest, and regression tests with fixed seeds. Every published figure is generated by a script. The validation suite is re-run at build time and its results are published on the site.

## X.4 Front end
`docs/` is the site, served by GitHub Pages from the `main` branch. Part 1 covers the contracts, the RAINMUMBAI comparison, the backtest, the live Chennai and Bengaluru prices, the forecast skill table and an interactive bond pricer with uncertainty bands. Part 2 covers the market inputs, an in-browser game-option pricer, the penalty and volatility structure, the four-method comparison and the validation suite. Chennai and Bengaluru are labelled constructed analogues and every Module C result is labelled hypothetical, everywhere they appear.

## X.5 Deliverables
Source and tests; processed data tables; the site; `docs/notes/methodology.md` and `docs/notes/assumptions.md`; `data/raw/README.md` for provenance; `README.md` for setup.

## X.6 Scheduled refresh (**new**)
`.github/workflows/update-data.yml` runs daily at 10:00 IST and updates **Part 1 only**.

- `scripts/refresh_current_season.py` re-fetches the provisional tail and the climate indices without re-reading the 45 archive grids, which are not in the repository.
- `scripts/build_weather_data.py` rebuilds `docs/data/weather.json`.
- `scripts/check_freshness.py` fails the job if any city's newest observation is more than six days old, or if a city has no days for a season that has already started. A cron that commits whatever it got is worse than no cron: the page would then show an old number under a new date.
- The test suite runs before anything is committed, and nothing is committed when nothing changed.

Part 2 is deliberately **not** scheduled: its market inputs are entered by hand because every programmatic NIFTY source was blocked, and a hypothetical contract re-priced daily would confer an authority it has not earned. Mumbai's season is closed until June 2027 and does not move either.
