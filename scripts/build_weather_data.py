"""Build docs/data/weather.json: Module A indices and fits, Module B prices,
and the RAINMUMBAI actual-versus-model comparison.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from src.a_rainfall.data import load_cached_series
from src.a_rainfall.fit import cross_city_correlation, fit_city, trend_report
from src.a_rainfall.indices import build_city_index, season_day_labels
from src.b_bonds.contracts import ParametricBond, WeatherCouponBond
from src.b_bonds.futures import FuturesModel, backtest, expiry_date, monthly_contracts
from src.b_bonds.premium import PremiumRule
from src.b_bonds.pricer import price_coupon_bond, price_parametric
from src.common.paths import SITE_DATA, ensure_dirs, load_config

ASOF = pd.Timestamp("2026-10-13")
QGRID = np.round(np.linspace(0.001, 0.999, 251), 6)


def quantile_grid(dist) -> dict:
    return {"q": [float(q) for q in QGRID],
            "x": [float(v) for v in dist.ppf(QGRID)]}


def city_payload(key: str, cfg: dict, fcfg: dict) -> dict:
    frame, ref = load_cached_series(key)
    ci = build_city_index(key, frame, ref)
    dists = fit_city(key, ci.table)
    city_cfg = cfg["cities"][key]
    contract = dict(city_cfg["contract"])
    contract["anchor_mm"] = ci.anchor_mm
    fc = fcfg[key]

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
        "forecast": fc,
    }

    # ---- current season path and a few reference seasons ---------------------
    current_year = ASOF.year
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
    hist = {}
    complete = ci.table[ci.table["complete"] & ~ci.table["provisional"]]
    picks = {"wettest": int(complete["SEAS_TOTAL"].idxmax()),
             "driest": int(complete["SEAS_TOTAL"].idxmin()),
             "median": int(complete["SEAS_TOTAL"].sub(complete["SEAS_TOTAL"].median()).abs().idxmin())}
    for name, year in picks.items():
        p = ci.cdr_path(year)
        hist[name] = {"year": year,
                      "spot": [float(v) for v in p["spot_mm"]],
                      "total": float(ci.table.loc[year, "SEAS_TOTAL"])}
    payload["reference_seasons"] = hist

    # ---- Module B3: the index future ----------------------------------------
    months = {"Jun": 6, "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}
    contract_months = [months[m] for m in contract["months"]]
    model = FuturesModel(ci, forecast_factor=float(fc["forecast_factor"]),
                         risk_lambda=float(fc["risk_lambda"]), use_trend=False)
    trend_model = FuturesModel(ci, forecast_factor=float(fc["forecast_factor"]),
                               risk_lambda=float(fc["risk_lambda"]), use_trend=True)
    season_dates = pd.date_range(f"{current_year}-{ci.window[0]}", f"{current_year}-{ci.window[1]}")
    band = fc["forecast_band"]
    payload["futures"] = {
        "multiplier_inr_per_mm": contract["multiplier_inr_per_mm"],
        "contracts": monthly_contracts(ci, current_year, contract_months, model, ASOF),
        "contracts_exante": monthly_contracts(ci, current_year, contract_months, model, ASOF,
                                              value_at="season_start"),
        "contracts_trend": monthly_contracts(ci, current_year, contract_months, trend_model, ASOF,
                                             value_at="season_start"),
        "valuation_now": model.fair_value(current_year, min(ASOF, season_dates[-1]), season_dates[-1]),
        "scenarios": [
            {"label": label, "factor": float(f),
             **FuturesModel(ci, forecast_factor=float(f),
                            risk_lambda=float(fc["risk_lambda"]),
                            use_trend=False).fair_value(
                 current_year, min(ASOF, season_dates[-1]), season_dates[-1])}
            for label, f in (("forecast low", band[0]), ("forecast centre", fc["forecast_factor"]),
                             ("forecast high", band[1]))],
        "monthly_asof": [
            {"asof": d.strftime("%Y-%m-%d"),
             **model.fair_value(current_year, d, season_dates[-1])}
            for d in pd.DatetimeIndex([season_dates[0] - pd.Timedelta(days=1)]).append(
                pd.date_range(season_dates[0], min(ASOF, season_dates[-1]), freq="MS")).unique()],
        "backtest": backtest(ci, 1991, current_year - 1,
                             multiplier=contract["multiplier_inr_per_mm"]),
    }

    # ---- Module B1/B2: bonds -------------------------------------------------
    bcfg = load_config("bonds")
    rate = float(bcfg["discount"]["rate"])
    coll = float(bcfg["collateral_yield"])
    rules = ([PremiumRule.r1(m) for m in bcfg["premium_rules"]["r1_multiples"]]
             + [PremiumRule.wang(l) for l in bcfg["premium_rules"]["wang_lambdas"]]
             + [PremiumRule.sd_load(b) for b in bcfg["premium_rules"]["sd_betas"]])
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
                        res = price_parametric(bond, dist, rule, rate, coll, method,
                                               n_paths=60_000)
                        entry["results"].append(res.to_dict())
                base_bond = ParametricBond(key, spec["trigger"], attach, exhaust,
                                           int(spec["tenors"][0]), inverted=inverted)
                del base_bond
            # attachment sensitivity at the default rule and shortest tenor
            default = bcfg["premium_rules"]["default"]
            rule = PremiumRule.wang(float(default["lam"]))
            for qa in (0.60, 0.70, 0.80, 0.90, 0.95) if not inverted else (0.40, 0.30, 0.20, 0.10, 0.05):
                a = float(dist.ppf(qa))
                e = exhaust
                if (not inverted and e <= a) or (inverted and e >= a):
                    continue
                b = ParametricBond(key, spec["trigger"], a, e, int(spec["tenors"][0]),
                                   inverted=inverted)
                r = price_parametric(b, dist, rule, rate, coll, "mc", n_paths=40_000)
                entry["sensitivity"].append({"quantile_attach": qa, "attach_mm": a,
                                             "expected_loss_annual": r.expected_loss_annual,
                                             "fair_spread": r.fair_spread,
                                             "prob_attach": r.prob_attach,
                                             "prob_exhaust": r.prob_exhaust})
            bonds_out[name] = entry
        else:
            dist = dists[spec["trigger"]]
            strike = float(dist.ppf(spec["strike_quantile"]))
            cap = float(strike - dist.ppf(spec["cap_quantile"]))
            bond = WeatherCouponBond(key, spec["trigger"], strike, cap, float(spec["kappa"]),
                                     float(spec["c_fixed"]), int(spec["tenors"][0]))
            bonds_out[name] = {"spec": spec, "strike_mm": strike, "cap_mm": cap,
                               "results": [price_coupon_bond(bond, dist, rate, m, 60_000)
                                           for m in ("burn", "mc")]}
    payload["bonds"] = bonds_out
    return payload, ci


def main() -> None:
    ensure_dirs()
    cfg = load_config("cities")
    fcfg = load_config("forecasts")
    bcfg = load_config("bonds")
    cities, tables = {}, {}
    for key in cfg["cities"]:
        print("building", key, flush=True)
        payload, ci = city_payload(key, cfg, fcfg)
        cities[key] = payload
        tables[key] = ci.table

    mum = cities["mumbai"]
    actual = fcfg["mumbai"]["season_2026_actual"]
    sep = expiry_date(2026, 9)
    model_fv = mum["futures"]["backtest"]["rows"]
    model_2026 = [r for r in mum["futures"]["contracts"] if r["month"] == 9]
    anchor = mum["anchor_mm"]
    official = float(actual["station_mean_mm"])
    proxy = float([r for r in mum["indices"] if r["year"] == 2026][0]["SEAS_TOTAL"])
    mult = float(mum["contract"]["multiplier_inr_per_mm"])
    comparison = {
        "contract": "RAINMUMBAI Sep 2026",
        "expiry": sep.strftime("%Y-%m-%d"),
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
        "model_fair_value_with_trend_mm": [r for r in mum["futures"]["contracts_trend"]
                                           if r["month"] == 9][0]["fair_value_mm"],
        "monthly_exante": mum["futures"]["contracts_exante"],
        "note": ("The season is over, so the Sep-2026 settlement is known.  The official "
                 "figure is the simple mean of IMD's Colaba and Santacruz seasonal totals, "
                 "the basis the contract settles on.  NCDEX's daily futures quotes are not "
                 "published in a form that could be retrieved here, so the comparison is "
                 "model fair value against the realised settlement price, not against "
                 "intraday marks."),
    }
    del model_fv, model_2026

    out = {
        "meta": {
            "asof": ASOF.strftime("%Y-%m-%d"),
            "baseline": cfg["baseline"],
            "discount": bcfg["discount"],
            "premium_defaults": bcfg["premium_rules"],
            "data_register": [
                {"source": "IMD gridded daily rainfall, 0.25 deg, 1901-present (imdlib)",
                 "use": "Module A archive, 1981-2025", "status": "downloaded and used"},
                {"source": "IMD real-time gridded rainfall",
                 "use": "current season", "status": "server timed out on 13 Oct 2026; not used"},
                {"source": "NASA POWER PRECTOTCORR (MERRA-2)",
                 "use": "current season stand-in, bias-corrected onto the settlement normal",
                 "status": "used for 2026 days"},
                {"source": "IMD station data (Colaba, Santacruz, Nungambakkam)",
                 "use": "settlement basis and 2026 actuals",
                 "status": "not machine-readable; published seasonal totals taken from IMD-sourced reports"},
                {"source": "NCDEX RAINMUMBAI product note and spot methodology",
                 "use": "contract terms and the 2,206.7 mm anchor", "status": "used"},
                {"source": "IMD north-east monsoon outlook, 1 Oct 2026",
                 "use": "Chennai and Bengaluru forecast factor", "status": "used"},
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


if __name__ == "__main__":
    main()
