"""Build docs/data/weather.json: Module A indices, fits and tails, the seasonal
forecast and its out-of-sample scores, Module B prices with parameter
uncertainty, and the RAINMUMBAI actual-versus-model comparison.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from src.a_rainfall.climate import SOURCES as CLIMATE_SOURCES
from src.a_rainfall.climate import load_all, season_state, state_table
from src.a_rainfall.data import load_cached_series
from src.a_rainfall.fit import (cross_city_correlation, fit_city, peaks_over_threshold,
                                trend_report)
from src.a_rainfall.indices import build_city_index, season_day_labels
from src.b_bonds import forecast as F
from src.b_bonds.contracts import ParametricBond, WeatherCouponBond
from src.b_bonds.futures import FuturesModel, backtest, expiry_date, monthly_contracts
from src.b_bonds.premium import PremiumRule
from src.b_bonds.pricer import (price_coupon_bond, price_parametric,
                                price_with_parameter_uncertainty)
from src.common.paths import SITE_DATA, ensure_dirs, load_config

ASOF = pd.Timestamp(os.environ.get("MONSOONRISK_ASOF")
                    or pd.Timestamp.utcnow().tz_localize(None).normalize())
SEASON_YEAR = 2026        # the season the RAINMUMBAI comparison is about
QGRID = np.round(np.linspace(0.001, 0.999, 251), 6)
N_BOOT = int(os.environ.get("MONSOONRISK_NBOOT", "200"))


def quantile_grid(dist) -> dict:
    return {"q": [float(q) for q in QGRID], "x": [float(v) for v in dist.ppf(QGRID)]}


def city_payload(key: str, cfg: dict, fcfg: dict, climate: dict) -> tuple[dict, object]:
    frame, ref = load_cached_series(key)
    ci = build_city_index(key, frame, ref)
    dists = fit_city(key, ci.table)
    city_cfg = cfg["cities"][key]
    contract = dict(city_cfg["contract"])
    contract["anchor_mm"] = ci.anchor_mm
    fc_cfg = fcfg[key]
    current_year = ASOF.year
    start_month = int(ci.window[0][:2])

    # ---- Module A ------------------------------------------------------------
    labels = season_day_labels(ci.window)
    payload = {
        "key": key,
        "label": ci.label,
        "window": list(ci.window),
        "season_basis": city_cfg["season_basis"],
        "anchor_mm": ci.anchor_mm,
        "grid_season_normal_mm": ci.grid_lpa_mm,
        "station_normal_mm": city_cfg.get("station_normal_mm"),
        "station_normal_source": city_cfg.get("station_normal_source"),
        "bias": ci.bias,
        "cell": {"lat": float(frame["cell_lat"].iloc[0]), "lon": float(frame["cell_lon"].iloc[0])},
        "contract": contract,
        "window_table": ci.window_table,
        "provisional_from": ci.provisional_from.strftime("%Y-%m-%d") if ci.provisional_from is not None else None,
        "lpa_daily": [{"md": md, "mm": float(ci.lpa.loc[md])} for md in labels],
        "indices": json.loads(ci.table.to_json(orient="records")),
        "fits": {k: v.to_dict() for k, v in dists.items()},
        "quantile_grids": {k: quantile_grid(v) for k, v in dists.items()},
        "trend": {ix: trend_report(ci.table, ix) for ix in ("SEAS_TOTAL", "MAX3")},
        "forecast_config": fc_cfg,
    }

    # Peaks-over-threshold tail cross-check at three thresholds (the standard
    # stability diagnostic: a good threshold is one where the fit stops moving).
    payload["pot"] = {
        "MAX3": [p for p in (peaks_over_threshold(ci.daily, ci.window, q, horizon_days=3)
                             for q in (0.90, 0.95, 0.975)) if p],
        "MAX1": [p for p in (peaks_over_threshold(ci.daily, ci.window, q, horizon_days=1)
                             for q in (0.90, 0.95, 0.975)) if p],
    }

    # ---- current season path and reference seasons ---------------------------
    path = ci.cdr_path(current_year)
    payload["current_season"] = {
        "year": int(current_year),
        "path": [{"date": d.strftime("%Y-%m-%d"), "rain": float(r), "lpa": float(l),
                  "spot": float(s)}
                 for d, r, l, s in zip(path["date"], path["rain_mm"], path["lpa_mm"],
                                       path["spot_mm"])],
        "days_elapsed": int(len(path)),
        "days_in_season": int(len(labels)),
    }
    complete = ci.table[ci.table["complete"] & ~ci.table["provisional"]]
    picks = {"wettest": int(complete["SEAS_TOTAL"].idxmax()),
             "driest": int(complete["SEAS_TOTAL"].idxmin()),
             "median": int(complete["SEAS_TOTAL"].sub(complete["SEAS_TOTAL"].median()).abs().idxmin())}
    payload["reference_seasons"] = {
        name: {"year": year, "spot": [float(v) for v in ci.cdr_path(year)["spot_mm"]],
               "total": float(ci.table.loc[year, "SEAS_TOTAL"])}
        for name, year in picks.items()}

    # ---- the seasonal forecast ----------------------------------------------
    years = sorted(set(ci.table["year"].tolist() + [current_year]))
    climate_tbl = state_table(years, start_month, climate)
    fc = F.build(key, ci.table, climate_tbl, ci.anchor_mm)
    state_now = season_state(current_year, start_month, climate)
    factor_now = fc.factor(state_now.to_dict(), current_year)
    lookup = (lambda y: season_state(int(y), start_month, climate).to_dict())
    walk = F.walk_forward(ci.table, climate_tbl, ci.anchor_mm, lookup, 1991, current_year)
    payload["forecast"] = {
        **fc.to_dict(),
        "state_now": state_now.to_dict(),
        "factor_now": factor_now,
        "walk_forward": walk,
        "predictor_months": state_now.nino34_months,
        "imd_category_factor": float(fc_cfg["forecast_factor"]),
        "imd_category_band": [float(b) for b in fc_cfg["forecast_band"]],
    }

    # ---- Module B3: the index future ----------------------------------------
    months = {"Jun": 6, "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}
    contract_months = [months[m] for m in contract["months"]]
    band = fc_cfg["forecast_band"]
    lam = float(fc_cfg["risk_lambda"])
    imd_model = FuturesModel(ci, forecast_factor=float(fc_cfg["forecast_factor"]),
                             risk_lambda=lam, forecast_label="IMD category centre")
    stat_model = FuturesModel(ci, forecast_factor=float(factor_now["factor"]),
                              risk_lambda=lam, forecast_label=factor_now["variant"])
    season_dates = pd.date_range(f"{current_year}-{ci.window[0]}", f"{current_year}-{ci.window[1]}")
    end = season_dates[-1]
    payload["futures"] = {
        "multiplier_inr_per_mm": contract["multiplier_inr_per_mm"],
        "contracts": monthly_contracts(ci, current_year, contract_months, imd_model, ASOF),
        "contracts_exante": monthly_contracts(ci, current_year, contract_months, imd_model,
                                              ASOF, value_at="season_start"),
        "contracts_forecast": monthly_contracts(ci, current_year, contract_months, stat_model,
                                                ASOF, value_at="season_start"),
        "valuation_now": imd_model.fair_value(current_year, min(ASOF, end), end),
        "valuation_now_forecast": stat_model.fair_value(current_year, min(ASOF, end), end),
        "scenarios": [
            {"label": label, "factor": float(f),
             **FuturesModel(ci, forecast_factor=float(f), risk_lambda=lam).fair_value(
                 current_year, min(ASOF, end), end)}
            for label, f in (("forecast low", band[0]),
                             ("forecast centre", fc_cfg["forecast_factor"]),
                             ("forecast high", band[1]))],
        "backtest": backtest(ci, 1991, current_year - 1,
                             multiplier=contract["multiplier_inr_per_mm"],
                             walk_forward_rows=walk),
    }

    # ---- Module B1/B2: bonds -------------------------------------------------
    bcfg = load_config("bonds")
    rate = float(bcfg["discount"]["rate"])
    coll = float(bcfg["collateral_yield"])
    rules = ([PremiumRule.r1(m) for m in bcfg["premium_rules"]["r1_multiples"]]
             + [PremiumRule.wang(l) for l in bcfg["premium_rules"]["wang_lambdas"]]
             + [PremiumRule.sd_load(b) for b in bcfg["premium_rules"]["sd_betas"]])
    default_rule = PremiumRule.wang(float(bcfg["premium_rules"]["default"]["lam"]))
    bonds_out = {}
    for name, spec in bcfg["bonds"].items():
        dist = dists[spec["trigger"]]
        if spec["type"] == "parametric":
            inverted = bool(spec.get("inverted", False))
            attach = float(dist.ppf(spec["quantile_attach"]))
            exhaust = float(dist.ppf(spec["quantile_exhaust"]))
            entry = {"spec": spec, "attach_mm": attach, "exhaust_mm": exhaust,
                     "trigger": spec["trigger"], "inverted": inverted, "results": [],
                     "sensitivity": []}
            for tenor in spec["tenors"]:
                bond = ParametricBond(key, spec["trigger"], attach, exhaust, int(tenor),
                                      inverted=inverted)
                for method in ("burn", "mc", "analytic"):
                    for rule in rules:
                        entry["results"].append(
                            price_parametric(bond, dist, rule, rate, coll, method,
                                             n_paths=60_000).to_dict())
            base_bond = ParametricBond(key, spec["trigger"], attach, exhaust,
                                       int(spec["tenors"][0]), inverted=inverted)
            entry["uncertainty"] = price_with_parameter_uncertainty(
                base_bond, dist, default_rule, rate, coll, n_boot=N_BOOT)
            for qa in ((0.60, 0.70, 0.80, 0.90, 0.95) if not inverted
                       else (0.40, 0.30, 0.20, 0.10, 0.05)):
                a = float(dist.ppf(qa))
                if (not inverted and exhaust <= a) or (inverted and exhaust >= a):
                    continue
                r = price_parametric(ParametricBond(key, spec["trigger"], a, exhaust,
                                                    int(spec["tenors"][0]), inverted=inverted),
                                     dist, default_rule, rate, coll, "mc", n_paths=40_000)
                entry["sensitivity"].append({"quantile_attach": qa, "attach_mm": a,
                                             "expected_loss_annual": r.expected_loss_annual,
                                             "fair_spread": r.fair_spread,
                                             "prob_attach": r.prob_attach,
                                             "prob_exhaust": r.prob_exhaust})
            bonds_out[name] = entry
        else:
            strike = float(dist.ppf(spec["strike_quantile"]))
            cap = float(strike - dist.ppf(spec["cap_quantile"]))
            bond = WeatherCouponBond(key, spec["trigger"], strike, cap, float(spec["kappa"]),
                                     float(spec["c_fixed"]), int(spec["tenors"][0]))
            bonds_out[name] = {"spec": spec, "strike_mm": strike, "cap_mm": cap,
                               "results": [price_coupon_bond(bond, dist, rate, m, 60_000)
                                           for m in ("burn", "mc")]}
    payload["bonds"] = bonds_out
    return payload, ci


def mumbai_season_contracts(cfg: dict, fcfg: dict, climate: dict, year: int) -> dict:
    """Mumbai's contract months for one season, marked the day before it opened.

    Kept separate from the current-year block so that rebuilding on a later date
    does not silently re-point the RAINMUMBAI comparison at a different season.
    """
    frame, ref = load_cached_series("mumbai")
    ci = build_city_index("mumbai", frame, ref)
    start_month = int(ci.window[0][:2])
    years = sorted(set(ci.table["year"].tolist() + [year]))
    climate_tbl = state_table(years, start_month, climate)
    fc = F.build("mumbai", ci.table, climate_tbl, ci.anchor_mm)
    factor = fc.factor(season_state(year, start_month, climate).to_dict(), year)
    months = [6, 7, 8, 9]
    plain = FuturesModel(ci, forecast_factor=1.0)
    tilted = FuturesModel(ci, forecast_factor=float(factor["factor"]),
                          forecast_label=factor["variant"])
    asof = pd.Timestamp(f"{year}-12-31")
    return {
        "climatology": monthly_contracts(ci, year, months, plain, asof, value_at="season_start"),
        "forecast": monthly_contracts(ci, year, months, tilted, asof, value_at="season_start"),
        "factor": factor,
    }


def main() -> None:
    ensure_dirs()
    cfg = load_config("cities")
    fcfg = load_config("forecasts")
    bcfg = load_config("bonds")
    climate = load_all(refresh=os.environ.get("MONSOONRISK_REFRESH") == "1")
    cities, tables = {}, {}
    for key in cfg["cities"]:
        print("building", key, flush=True)
        payload, ci = city_payload(key, cfg, fcfg, climate)
        cities[key] = payload
        tables[key] = ci.table

    # The comparison is about the 2026 season specifically, so it is computed for
    # that year rather than for whatever year the build happens to run in.
    mum = cities["mumbai"]
    actual = fcfg["mumbai"]["season_2026_actual"]
    anchor = mum["anchor_mm"]
    official = float(actual["station_mean_mm"])
    proxy = float([r for r in mum["indices"] if r["year"] == SEASON_YEAR][0]["SEAS_TOTAL"])
    mult = float(mum["contract"]["multiplier_inr_per_mm"])
    mum_exante = mumbai_season_contracts(cfg, fcfg, climate, SEASON_YEAR)
    forecast_sep = [r for r in mum_exante["forecast"] if r["month"] == 9][0]
    comparison = {
        "contract": "RAINMUMBAI Sep 2026",
        "expiry": expiry_date(2026, 9).strftime("%Y-%m-%d"),
        "official_settlement_mm": official,
        "official_components": actual,
        "anchor_mm": anchor,
        "model_fair_value_season_start_mm": anchor,
        "model_error_mm": anchor - official,
        "model_error_inr_per_lot": (anchor - official) * mult,
        "contract_value_at_settlement_inr": official * mult,
        "contract_value_at_anchor_inr": anchor * mult,
        "gridded_proxy_settlement_mm": proxy,
        "gridded_proxy_error_mm": proxy - official,
        "model_fair_value_with_forecast_mm": forecast_sep["fair_value_mm"],
        "forecast_variant": mum_exante["factor"]["variant"],
        "forecast_error_mm": forecast_sep["fair_value_mm"] - official,
        "monthly_exante": mum_exante["climatology"],
        "note": ("The season is over, so the Sep-2026 settlement is known.  The official "
                 "figure is the simple mean of IMD's Colaba and Santacruz seasonal totals, "
                 "the basis the contract settles on.  NCDEX's daily futures quotes are not "
                 "published in a form that could be retrieved here, so the comparison is "
                 "model fair value against the realised settlement price, not against "
                 "intraday marks."),
    }

    out = {
        "meta": {
            "asof": ASOF.strftime("%Y-%m-%d"),
            # Stamp the data, not the clock: a wall-clock stamp would make the
            # scheduled job commit a diff every day even when nothing moved.
            "data_through": max(c["current_season"]["path"][-1]["date"]
                                for c in cities.values()
                                if c["current_season"]["path"]),
            "baseline": cfg["baseline"],
            "discount": bcfg["discount"],
            "premium_defaults": bcfg["premium_rules"],
            "bootstrap_resamples": N_BOOT,
            "climate_sources": {k: v["label"] for k, v in CLIMATE_SOURCES.items()},
            "data_register": [
                {"source": "IMD gridded daily rainfall, 0.25 deg, 1901-present (imdlib)",
                 "use": "Module A archive, 1981-2025", "status": "downloaded and used"},
                {"source": "IMD real-time gridded rainfall",
                 "use": "current season", "status": "server timed out on 13 Oct 2026; not used"},
                {"source": "NASA POWER PRECTOTCORR (MERRA-2)",
                 "use": "current season stand-in, bias-corrected onto the settlement normal",
                 "status": "used for 2026 days"},
                {"source": "NOAA PSL Nino 3.4 SST anomaly",
                 "use": "seasonal forecast predictor", "status": "used; current to the previous month"},
                {"source": "NOAA PSL Dipole Mode Index (HadISST)",
                 "use": "seasonal forecast predictor",
                 "status": "used in the backtest; lags several months, so often unavailable for a season now starting"},
                {"source": "IMD station data (Colaba, Santacruz, Nungambakkam)",
                 "use": "settlement basis and 2026 actuals",
                 "status": "not machine-readable; published seasonal totals taken from IMD-sourced reports"},
                {"source": "NCDEX RAINMUMBAI product note and spot methodology",
                 "use": "contract terms and the 2,206.7 mm anchor", "status": "used"},
                {"source": "IMD north-east monsoon outlook, 1 Oct 2026",
                 "use": "Chennai and Bengaluru forecast band", "status": "used"},
            ],
        },
        "cities": cities,
        "cross_city": {"SEAS_TOTAL": cross_city_correlation(tables, "SEAS_TOTAL"),
                       "MAX3": cross_city_correlation(tables, "MAX3")},
        "rainmumbai_comparison": comparison,
    }
    path = os.path.join(SITE_DATA, "weather.json")
    with open(path, "w") as fh:
        json.dump(out, fh, separators=(",", ":"), allow_nan=False, default=str)
    print("wrote", path, round(os.path.getsize(path) / 1e6, 2), "MB")
    for key, city in cities.items():
        f = city["forecast"]
        print(f"  {key}: forecast={f['selected']} factor_now={f['factor_now']['factor']:.4f}"
              f" ({f['factor_now']['reason']})")


if __name__ == "__main__":
    main()
