# Assumption log

Every modelling choice that is not forced by the data, with the reason. Dates are
when the choice was made. Changing any of these changes published numbers.

| Date | Choice | Value | Why |
|---|---|---|---|
| 2026-10-13 | Baseline period for the daily normal | 1991–2020 | The period RAINMUMBAI's 2,206.7 mm anchor is stated on. |
| 2026-10-13 | History used for index distributions | 1981–2025 | 45 complete seasons; earlier IMD years exist but add download time without adding much to a 30-year-anchored contract. |
| 2026-10-13 | Smoothing of the daily normal | centred 15-day moving average | Raw daily means over 30 years are noisy. The window is a config knob (`cities.yaml: smoothing_window`). |
| 2026-10-13 | Normal rescaled to the anchor | yes, over the season days | Smoothing moves a few mm across the season boundary. Rescaling makes the exchange's identity exact: end-of-season spot = realised seasonal rainfall. |
| 2026-10-13 | Grid-to-station bias correction | multiplicative, per source | A 0.25° cell is not the station a contract settles on. Each source is scaled so its own 1991–2020 seasonal normal equals the published station normal (Mumbai ×0.810, Chennai ×1.009). Bengaluru has no verified station normal and is left at ×1.000. |
| 2026-10-13 | Wet-day threshold | 2.5 mm | IMD's usual rain-day threshold. Diagnostics only. |
| 2026-10-13 | Bengaluru season window | chosen from data | Fewest months capturing ≥75% of annual rainfall: 1 Jun – 30 Nov, 78.7% of the annual total. |
| 2026-10-13 | Current-season data source | NASA POWER, flagged provisional | IMD's 2026 archive is unpublished and its real-time server did not respond. |
| 2026-10-13 | Futures fair value | spot + (factor−1)×remaining normal + trend + λ×σ | Under pure climatology the CDR future is a martingale, so every departure from spot has to be argued for: a published forecast, a fitted trend, or a risk premium. |
| 2026-10-13 | Forecast factor for Chennai and Bengaluru | 1.00, band 0.88–1.12 | IMD's 1 Oct 2026 north-east monsoon outlook: "normal", defined as 88–112% of the long-period average. |
| 2026-10-13 | Trend | Theil–Sen, used only when Mann–Kendall p < 0.10 | Robust to outliers; the significance gate stops noise being extrapolated. In the backtest the trend is refitted each year on prior seasons only. |
| 2026-10-13 | Risk premium λ on futures | 0 by default | There is no market to infer it from. It is a slider on the site instead of a hidden constant. |
| 2026-10-13 | Bond attachment / exhaustion | 90th / 99th percentile (flood), 10th / 1st (drought) | Roughly a 1-in-10 attachment and a 1-in-100 total loss, which is the range sponsored catastrophe bonds are usually structured in. |
| 2026-10-13 | Default risk premium rule | Wang transform, λ = 0.25 | Standard in insurance-linked securities. The multiple it implies (about 1.7× expected loss) is in the range quoted for catastrophe bonds. No Indian market exists to calibrate it. |
| 2026-10-13 | Discount and collateral rate | 5.60% | RBI repo 5.50% (7 Oct 2026) plus 10 bp as a 91-day T-bill proxy; the auction yield itself was not retrieved. |
| 2026-10-13 | Multi-year season dependence | independent | Lag-1 autocorrelation of seasonal totals is small; it is exported per city so the assumption can be checked. Cross-city Spearman correlations are exported too. |
| 2026-10-13 | Monte Carlo paths | 60,000 (build), 20,000 (browser) | Standard errors are reported; they are small against the modelling uncertainty. |
| 2026-10-13 | Game option dynamics | geometric Brownian motion | Baseline of the specification. No smile, no skew. |
| 2026-10-13 | Volatility input | India VIX, 15.16% | Realised volatility could not be computed (history download blocked). A volatility grid is published alongside. |
| 2026-10-13 | Tree steps | 2,000 (build), 600 (browser default) | Convergence study is published; the reference contract moves by less than 2% past 800 steps. |
| 2026-10-13 | Monte Carlo comparison | matched monitoring frequency | The number of decision dates is part of the contract: fewer dates means fewer chances for the issuer to cancel, so a 200-step Monte Carlo is compared with a 200-step tree. |
