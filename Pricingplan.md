# Plan: Pricing Monsoon-Linked Bonds and Game Options

Working title: **MonsoonRisk**. Companion document: `spec.md` (technical detail).

## 1. Objective

Build a transparent, reproducible pricing toolkit in Python with three modules:

- **Module A: Rainfall data and risk layer.** Turns free IMD rainfall data into season-level indices for Mumbai, Chennai and Bengaluru, and fits their distributions.
- **Module B: Weather bonds and cat bonds.** Prices rainfall-linked bonds (principal-at-risk and coupon-linked) for the three cities, using Module A's distributions.
- **Module C: Israeli (game) option on NIFTY 50.** Prices an American-style option that the issuer can also cancel for a penalty, which is a Dynkin game. Independent of Modules A and B.

## 2. Scope

**In scope**
- Rainfall indices for Mumbai (modelled on the traded RAINMUMBAI contract) and constructed analogues for Chennai and Bengaluru.
- A baseline method (burn analysis plus fitted distributions) for Module B, and a daily rainfall simulator as an upgrade.
- Game option solver with several methods that cross-check each other, applied to NIFTY 50.
- A short methodology write-up and, if time allows, a small web front end.

**Out of scope (decided in discussion)**
- A weather-linked callable/puttable bond priced as a game option (the "bridge" idea). It needs its own pricing-measure argument and would dominate the project.
- Day-to-day weather forecasting. Forecast data is only an optional update layer, not a core input.
- Trading, investment advice, or calibration to live bond prices. India has no cat bond market, so Module B is model-based.

**Honesty note.** Claims that something is "new" or "not freely available" come from the searches done in this conversation. They mean "I did not find it," not "it does not exist."

## 3. Modules at a glance

| | Module A | Module B | Module C |
|---|---|---|---|
| Purpose | Rainfall indices and distributions | Price weather and cat bonds | Price game option on NIFTY 50 |
| Main inputs | IMD gridded daily rainfall | Distributions from A, bond terms, discount rate, risk-premium rule | NIFTY 50 history, India VIX, T-bill yield, dividend yield, contract terms |
| Main outputs | Season index tables, fitted distributions, optional simulator | Price, fair spread, expected loss, attachment/exhaustion probabilities, loss curves | Price with error bars, exercise and cancellation boundaries, Greeks |
| Depends on | None | A | None |

## 4. Repository layout

```
monsoonrisk/
  config/            # cities.yaml, bonds.yaml, game_option.yaml
  data/raw/          # untouched downloads, never edited
  data/processed/    # derived tables (csv/parquet)
  src/
    a_rainfall/      # data.py, indices.py, fit.py, simulate.py
    b_bonds/         # contracts.py, premium.py, pricer.py, validate.py
    c_game/          # binomial.py, lsm.py, dual.py, nifty.py, validate.py
    common/          # discounting.py, stats.py, plotting.py
  tests/
  notebooks/
  app/               # optional web front end
  docs/              # methodology write-up, figures
  plan.md  spec.md  README.md
```

## 5. Phases

Effort figures are rough guesses for one person working part-time; adjust to your schedule.

### Phase 0: Setup and data check (about 0.5 week)
- Create the repo, environment (Python 3.11+, numpy, scipy, pandas, xarray, imdlib, matplotlib, pytest; QuantLib-Python optional) and config files.
- Confirm `imdlib` downloads rainfall for 1901 to the latest year and extracts one city cell.
- **Exit:** one city's daily rainfall series loads and plots.

### Phase 1: Module A baseline (about 1.5 weeks)
- Pull gridded rainfall for the cells nearest Mumbai, Chennai and Bengaluru.
- Build the daily long-period average (LPA) from 1991 to 2020 and the index builder (cumulative deviation, seasonal total, heaviest 1-day and 3-day rainfall).
- Choose each city's season window from data (see spec section A.4).
- Fit and select distributions for each index; produce diagnostics.
- **Exit:** a clean season-index table per city and a fitted distribution with goodness-of-fit plots. Mumbai's seasonal LPA is compared against the reported 2,206.7 mm figure.

### Phase 2: Module B version 1 (about 2 weeks)
- Implement contracts (principal-at-risk bond, coupon-linked bond, optional index future) and three risk-premium rules.
- Price from burn analysis and from fitted distributions, with analytic and Monte Carlo methods.
- Run all three cities; produce sensitivity tables and a loss-exceedance plot per city.
- **Exit:** all tests in spec section B.9 pass; the three methods agree within stated tolerances.

### Phase 3: Module C (about 2.5 weeks)
- Binomial game-option solver, then Longstaff-Schwartz Monte Carlo, then pathwise dual bounds.
- Validate on limiting cases (see spec section C.6), then apply to NIFTY 50 with market-derived inputs.
- **Exit:** methods agree, convergence plots are produced, and a price table over strike, tenor, volatility and penalty is generated.

### Phase 4: Upgrades (stretch, about 2 weeks)
- Module A daily rainfall simulator with a season-level factor, validated against Phase 1's baseline.
- Re-price Module B with simulated seasons and compare.
- Optional: finite-difference solver for Module C; Heston extension for NIFTY.

### Phase 5: Packaging (about 1.5 weeks)
- Methodology write-up, README, reproducibility script, and optional web front end.

## 6. Cut order if time runs short

1. Web front end
2. Phase 4 upgrades (simulator, finite difference, Heston)
3. Dual-bound method in Module C
4. Multi-city basket bond and index future in Module B

Never cut: Module A baseline, Module B version 1 with tests, Module C binomial and Monte Carlo solvers with validation.

## 7. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Gridded data does not match station readings (RAINMUMBAI settles on Santacruz and Colaba stations) | Compare Mumbai's seasonal LPA with the reported figure; test neighbouring cells; document the gap |
| No market prices for Indian cat bonds or analogue indices | Present results as model-based; show sensitivity to the risk-premium rule instead of claiming a "right" price |
| Short history makes tail estimates unreliable | Report confidence intervals via bootstrap; compare fitted-distribution results against burn analysis |
| Daily rainfall models can understate variability | Include a season-level factor; check variance of simulated seasonal totals against history |
| Game option has no market to calibrate against | Validate with limiting cases and cross-method agreement, not market fit |
| Data sources change or become unavailable | Cache raw downloads and record provenance in `data/raw/README` |
| Scope creep | Follow the cut order above; the bridge product stays out of scope |

## 8. Definition of done

- All three modules run end to end from a single script with fixed seeds.
- Every test in `spec.md` passes.
- Module B outputs exist for all three cities, with sensitivity tables to attachment, exhaustion and risk-premium parameters.
- Module C outputs include methods that agree, convergence plots, boundaries and Greeks.
- The write-up states every assumption, data source and known limitation.

## 9. Open decisions for you

1. Bond tenors to price (suggested: 1 and 3 years).
2. Risk-premium rule to present as the default (spec offers three).
3. Whether Bengaluru's season window is chosen purely from data (suggested) or by a rule you prefer.
4. Whether to include the optional index future for Mumbai as a sanity check against live prices (needs price data; availability not verified).

## 10. What was verified while planning

- `imdlib` is a Python package that downloads IMD gridded rainfall and temperature, reads them into xarray, and exports CSV or NetCDF; it also handles real-time gridded data.
- IMD's gridded rainfall is 0.25 degrees, 1901 to present.
- RAINMUMBAI: cumulative deviation from the long-period average over June to September, benchmarked on 1991 to 2020, settled on IMD Santacruz and Colaba data, with a multiplier of Rs 50 per mm.
- For the Tamil Nadu and Puducherry subdivision, October to December supplies about 48% of annual rainfall (IMD reports).
- Not verified: IMD station-level data access, ENSO/IOD data access, free historical NSE option-chain data, any live RAINMUMBAI price history.
