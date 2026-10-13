"""Module C market inputs for NIFTY 50.

Every number is dated and sourced in config/game_option.yaml.  Bulk NIFTY 50
history could not be downloaded on 13 Oct 2026 (Yahoo's chart API answered HTTP
429, and the NSE and niftyindices endpoints answered 503 and 302), so realised
volatility is not computed from returns: India VIX is the volatility input and
every price is also reported across a volatility grid.  Drop a CSV with
`date,close` at data/raw/nifty50_close.csv and realised volatility is picked up
automatically.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..common.paths import RAW, load_config


@dataclass
class NiftyInputs:
    asof: str
    s0: float
    sigma: float
    sigma_label: str
    r: float
    q: float
    realised_vol_1y: float | None
    realised_vol_3y: float | None
    sources: dict

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def realised_vol(window_years: float) -> float | None:
    path = os.path.join(RAW, "nifty50_close.csv")
    if not os.path.exists(path):
        return None
    frame = pd.read_csv(path, parse_dates=["date"]).sort_values("date")
    frame = frame[frame["date"] >= frame["date"].max() - pd.Timedelta(days=int(365 * window_years))]
    rets = np.diff(np.log(frame["close"].to_numpy(dtype=float)))
    return float(rets.std(ddof=1) * np.sqrt(252))


def load_inputs() -> NiftyInputs:
    cfg = load_config("game_option")["market"]
    return NiftyInputs(
        asof=str(cfg["asof"]),
        s0=float(cfg["s0"]),
        sigma=float(cfg["india_vix"]) / 100.0,
        sigma_label=f"India VIX {cfg['india_vix']} (implied, ~30 day)",
        r=float(cfg["risk_free"]),
        q=float(cfg["dividend_yield"]),
        realised_vol_1y=realised_vol(1),
        realised_vol_3y=realised_vol(3),
        sources={k: v for k, v in cfg.items() if str(k).endswith(("source", "note"))},
    )
