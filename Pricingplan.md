# Plan: Pricing Monsoon-Linked Bonds and Game Options

Working title: **MonsoonRisk**. Companion document: `Pricingspec.md` (technical detail).

**Status: delivered and live.** Repository <https://github.com/Khaja500/monsoonrisk>,
site <https://khaja500.github.io/monsoonrisk/>. Last revised 13 October 2026, after
the first round of post-delivery improvements described in section 7.

## 1. Objective

Build a transparent, reproducible pricing toolkit in Python with three modules:

- **Module A: Rainfall data and risk layer.** Turns free IMD rainfall data into season-level indices for Mumbai, Chennai and Bengaluru, and fits their distributions.
- **Module B: Weather bonds and cat bonds.** Prices rainfall-linked bonds (principal-at-risk and coupon-linked) for the three cities, using Module A's distributions.
- **Module C: Israeli (game) option on NIFTY 50.** Prices an American-style option that the issuer can also cancel for a penalty, which is a Dynkin game. Independent of Modules A and B.

All three are built, tested and published. The web front end, listed in the original
plan as "if time allows" and first in the cut order, was built: both parts re-price
in the browser from the same models.

## 2. Scope as delivered

**In scope and done**
- Rainfall indices for Mumbai (the traded RAINMUMBAI contract) and constructed analogues for Chennai and Bengaluru, on IMD gridded daily rainfall 1981–2025 plus a provisional 2026.
- Burn analysis, quadrature and Monte Carlo for Module B, under three risk-premium rules.
- Four methods for Module C: binomial tree, Longstaff–Schwartz, Crank–Nicolson with two obstacles, and a rigorous bracket.
- A methodology write-up (`docs/notes/methodology.md`), an assumption log (`docs/notes/assumptions.md`) and a web front end (`docs/`).

**Added after the original plan**
- **A seasonal forecast with content** (`src/b_bonds/forecast.py`). The original design took the forecast factor from IMD's categorical outlook, whose category centre is 1.00 — which makes the forecast term identically zero and the future identical to spot. Replaced with a regression on climate state known before the season opens (Niño 3.4, Dipole Mode Index), scored out of sample against climatology, with the variant selected walk-forward so neither the coefficients nor the choice of model sees the season being priced.
- **Parameter uncertainty on every bond curve** (`price_with_parameter_uncertainty`). Resample the 45 observed seasons, refit, re-price.
- **A peaks-over-threshold tail cross-check** (`peaks_over_threshold`), because annual maxima discard every large event in a season but the largest.
- **An averaged-lattice price for Module C** (`averaged_price`), because a double-obstacle lattice oscillates in the step count and a single fine tree is not a reference value.
- **A scheduled refresh** of the current season (`.github/workflows/update-data.yml`) with a freshness guard that fails rather than republishing stale data under a new date.

**Out of scope, and still out**
- A weather-linked callable/puttable bond priced as a game option (the "bridge" idea). It needs its own pricing-measure argument and would dominate the project.
- Day-to-day weather forecasting.
- Trading, investment advice, or calibration to live bond prices. India has no cat bond market, so Module B is model-based.

**Dropped from the original plan, with reasons**
- **The daily rainfall simulator** (old Phase 4). Not built. The baseline distribution layer plus the POT tail cross-check covers what Module B needs; the simulator earns its place only when a path-dependent product is priced. Still the first item in section 7.
- **Pathwise dual bounds for Module C** (Kühn, Kyprianou and van Schaik). Not built, and the reason is recorded rather than hidden: the paper was unavailable, and the obvious shortcut — freeze one side's policy, optimise the other by regression — produces a biased estimate whose bias runs the wrong way on the minimising side, so it is not a bound. A rigorous analytic bracket is published instead.
- **A Heston or local-volatility extension.** No free NSE option-chain history was obtainable, so any such model would carry a free parameter dressed as a calibration.

**Honesty note.** Claims that something is "new" or "not freely available" mean "I did not find it", not "it does not exist". Where a source was tried and failed, the failure is recorded in `data/raw/README.md` and in the data register on the site.

## 3. Modules at a glance

| | Module A | Module B | Module C |
|---|---|---|---|
| Purpose | Rainfall indices, distributions and tails | Price the index future and weather/cat bonds | Price game option on NIFTY 50 |
| Main inputs | IMD gridded daily rainfall; NOAA Niño 3.4 and DMI | Distributions from A, contract terms, discount rate, risk-premium rule, seasonal forecast | NIFTY 50 level, India VIX, T-bill yield, dividend yield, contract terms |
| Main outputs | Season index tables, fitted distributions, POT tails, forecast skill | Fair value and backtest for the future; price, fair spread, expected loss and uncertainty bands for bonds | Price with numerical uncertainty, boundaries, Greeks, four-method comparison |
| Depends on | None | A | None |

## 4. Repository layout (as built)

```
monsoonrisk/
  config/            cities.yaml, bonds.yaml, game_option.yaml, forecasts.yaml
  data/raw/          downloads, not committed except the climate and POWER caches
  data/processed/    extracted daily series (committed)
  src/
    a_rainfall/      data.py, indices.py, fit.py, climate.py
    b_bonds/         contracts.py, premium.py, pricer.py, futures.py, forecast.py
    c_game/          binomial.py, lsm.py, fd.py, dual.py, nifty.py
    common/          paths.py, discounting.py, stats.py
  scripts/           download_imd.py, extract_cities.py, refresh_current_season.py,
                     build_weather_data.py, build_game_data.py, check_freshness.py
  tests/             45 tests
  docs/              the site (GitHub Pages) + notes/methodology.md, notes/assumptions.md
  .github/workflows/ update-data.yml
  Pricingplan.md  Pricingspec.md  README.md
```

`src/a_rainfall/simulate.py` and `src/c_game/dual.py`'s dual-bound half are the two
pieces of the original layout that do not exist as specified; see section 2.

## 5. Phases and what came out of them

| Phase | Planned | Outcome |
|---|---|---|
| 0 Setup and data check | repo, environment, one city loading | Done. `imdlib` downloads and reads IMD 0.25° grids; 7 of 45 years needed a retry at lower parallelism. |
| 1 Module A baseline | indices and distributions for three cities | Done. Mumbai's **grid** seasonal normal is 2,723.5 mm against the contract's 2,206.7 mm — a 23% gap, handled by a per-source bias correction rather than ignored. Bengaluru's season window was selected from data: 1 Jun – 30 Nov, 78.7% of annual rainfall. |
| 2 Module B v1 | contracts, three premium rules, three methods | Done. Burn, quadrature and Monte Carlo agree within sampling error (4.03% / 4.11% / 4.12% expected loss on the default Mumbai flood bond). |
| 3 Module C | tree, Monte Carlo, bounds | Done, with finite differences replacing the dual bounds. All limiting cases pass. |
| 4 Upgrades | daily simulator, finite difference, Heston | Partly. Finite differences built; simulator and Heston not, for the reasons in section 2. |
| 5 Packaging | write-up, README, front end | Done, including the front end that was first in the cut order. |
| 6 Post-delivery (new) | forecast with content, uncertainty bands, tail cross-check, lattice averaging, scheduled refresh | Done. See section 7 for what the forecast work actually found. |

## 6. Findings

These are the results, including the ones that did not go the way the plan assumed.

**The model missed RAINMUMBAI by 36.85 mm, or ₹1,843 a lot.** The September 2026
contract settled at 2,243.55 mm (the mean of IMD's Colaba 1,957.1 and Santacruz
2,530.0). Climatology quoted the anchor, 2,206.70 mm, before the season opened.

**Under climatology every contract month prices at the anchor.** The expected
deviation is zero whatever the horizon, so June, July, August and September all
quote 2,206.7 — and settled at 2,025.7, 2,699.4, 2,480.0 and 2,243.55. The future
is a martingale under climatology, which is why a forecast term with content
matters so much.

**The seasonal forecast has little skill, and for Chennai none at all.** Scored
out of sample over 25 seasons against climatology:

| City | Best variant | RMSE skill vs climatology | Selected |
|---|---|---|---|
| Mumbai | linear trend | +5.4% | trend |
| Bengaluru | linear trend | +2.7% | trend |
| Chennai | — every variant is worse | −0.9% (best: ENSO) | climatology |

Niño 3.4 on its own is *worse* than climatology for Mumbai and Bengaluru, and the
Chennai NE-monsoon ratio has an out-of-sample RMSE of 0.59 — ±59% of the long-period
average. The honest conclusion is that for Chennai, IMD's categorical band really is
the best available statement, and the model says so rather than inventing a tilt. The
selection margin is also weak evidence: five candidates scored on 25 seasons, chosen
on the same scores they report.

**2026 was a strong El Niño.** Niño 3.4 reached +2.09 °C in September 2026 and the
JAS ONI +2.16, which is the backdrop to an all-India monsoon 12.6% below normal, the
worst since 2015, and Karnataka 35% below normal, its worst in 55 years. The model
does not get to use that as an excuse — it is exactly the state the ENSO predictor
was given and still failed to beat climatology with.

**The bonds are far less precisely priced than one curve suggests.** The default
Mumbai flood bond has an expected loss of 4.25%, and the 45-season record supports
anywhere between **1.50% and 7.24%**; the fair spread band is 2.8% to 11.3%. This is
now drawn on the site rather than left in the exported data.

**The at-the-money Israeli put is worth exactly the penalty.** The holder's payoff is
zero and the issuer's time value is not, so the issuer cancels at once: the price is
δ, in a straight line, until δ reaches 4.44% of spot, above which the cancellation
right is worthless and the price is the American value. Where that cap binds, vega,
rho and theta are all zero.

**The issuer's cancellation region collapses onto the strike.** Once the cap binds on
a region the value there is `G + δ`, which is linear away from the kink, so
continuation is linear too and the strict inequality survives only at the kink.

**Lattice oscillation, not method disagreement.** The published 3.5% gap between
Monte Carlo and the tree on the out-of-the-money contract was mostly an artefact of
comparing single resolutions. Averaging the tree over a band of step counts gives
154.6 ± 1.3 where single trees ranged 152.9 to 157.3. Smoothing the terminal payoff
(Broadie–Detemple) changes the answer by under 0.01 — a negative result worth
keeping, because it locates the oscillation in the free boundary rather than the
payoff kink.

## 7. Backlog, in priority order

1. **A daily rainfall simulator** (old Phase 4, spec A.7). The only route to pricing anything path-dependent, and a better tail for `MAX3` than 45 annual maxima.
2. **Station data instead of the grid.** The contract settles on Colaba and Santacruz; the model prices a grid cell 23% wetter, patched with a factor that fixes the mean and not the shape. The flood trigger is entirely a shape-of-the-tail question. Blocked on IMD data-portal access.
3. **Realised volatility for Module C.** Still not computed: Yahoo returns HTTP 429, NSE 503 and niftyindices 302. `src/c_game/nifty.py` picks up `data/raw/nifty50_close.csv` automatically if a `date,close` file is dropped there, which is the manual route until a source answers.
4. **Intra-season predictability.** Fair value mid-season is spot plus remaining climatology. Whether season-to-date carries information about the remainder is testable on 45 years and has never been tested here.
5. **Multi-city basket bond** on a Gaussian copula. The rank correlations are already computed (Mumbai–Chennai ρ = 0.30, p = 0.047; the other two pairs are not significant).
6. **Dual bounds for Module C**, properly, from the Kühn–Kyprianou–van Schaik construction. Academic completeness: the tree and finite differences already agree to under 0.3% on the well-behaved contracts.

## 8. Risks: which ones materialised

| Risk | Outcome |
|---|---|
| Gridded data does not match station readings | **Materialised, as expected.** 23% gap at Mumbai. Handled by a per-source bias correction; documented as fixing the mean, not the shape. |
| No market prices for Indian cat bonds | **Materialised.** All bond output is reported as sensitivities to the risk-premium rule, never as a price. |
| Short history makes tail estimates unreliable | **Materialised and now quantified.** Expected loss 4.25% with a 1.5–7.2% bootstrap band. |
| Daily rainfall models understate variability | Not reached — the simulator was not built. |
| Game option has no market to calibrate against | **Materialised.** Validated by limiting cases and cross-method agreement only. |
| Data sources change or become unavailable | **Materialised twice.** IMD's real-time grid timed out; every bulk NIFTY source refused. Both are recorded in the data register rather than worked around silently. |
| Scope creep | Contained. The bridge product stayed out. |

## 9. Definition of done: status

- [x] All three modules run end to end from scripts with fixed seeds.
- [x] Every test in `Pricingspec.md` passes — 45 tests.
- [x] Module B outputs exist for all three cities with sensitivity tables, and now with parameter-uncertainty bands.
- [x] Module C outputs include four methods that agree, convergence plots, boundaries and Greeks.
- [x] The write-up states every assumption, data source and known limitation, including the ones that failed.

## 10. Decisions that were open, and how they were settled

1. **Bond tenors.** 1 and 3 years, both priced.
2. **Default risk-premium rule.** R2, the Wang transform at λ = 0.25, which implies about 1.7× expected loss — in the range quoted for catastrophe bonds. All three rules are always shown together.
3. **Bengaluru's season window.** Chosen from data, as suggested: the fewest months capturing at least 75% of annual rainfall, which is 1 Jun – 30 Nov at 78.7%.
4. **The Mumbai index future as a sanity check.** Done, and it became the centre of the project: it is the one place where a model number meets a real settlement.

## 11. Verification log

**Verified in use**
- `imdlib` downloads IMD 0.25° gridded rainfall, 1901 to the latest published year, and reads it into xarray.
- RAINMUMBAI: cumulative deviation from the 1991–2020 long-period average over June–September, anchored at 2,206.7 mm, settled on the mean of IMD Santacruz and Colaba, ₹50 per mm, monthly contracts June–September.
- NOAA PSL publishes Niño 3.4 monthly to the previous month, and the HadISST Dipole Mode Index with a lag of several months.
- The Tamil Nadu and Puducherry October–December season supplies about 48% of annual rainfall; the Chennai (Nungambakkam) NE-monsoon normal is 75 cm.

**Tried and failed, on 13 October 2026**
- IMD real-time gridded rainfall: connection to `imdpune.gov.in` timed out.
- IMD station-level data (Colaba, Santacruz, Nungambakkam): no machine-readable access found; published seasonal totals taken from IMD-sourced reports instead.
- Bulk NIFTY 50 history: Yahoo chart API HTTP 429, NSE 503, niftyindices 302, stooq behind a proof-of-work challenge.
- NSE option-chain history: not found free, so no Heston calibration.
- RAINMUMBAI daily quote history: not published in any retrievable form, which is why the comparison is against the realised settlement rather than intraday marks.
