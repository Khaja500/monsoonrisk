"""Climate-state predictors: Nino 3.4 (ENSO) and the Dipole Mode Index (IOD).

The seasonal forecast term in the futures model needs a number that is known
*before* the season opens and that has some relationship with the season's
rainfall.  IMD's published outlook is categorical ("normal", 88-112% of the
long-period average), and its category centre contributes exactly nothing to a
fair value.  These two indices are quantitative, free, and long enough to be
backtested.

Publication lag matters and is handled explicitly: NOAA PSL's Nino 3.4 series
runs to the previous month, so it is available at the start of any season; the
HadISST-based Dipole Mode Index lags by several months, so it is usable in a
backtest but often not for a season that is starting now.  `season_state`
reports which predictors were actually available rather than quietly filling
them in.
"""
from __future__ import annotations

import os
import urllib.request
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..common.paths import RAW

SOURCES = {
    "nino34": {
        "url": "https://psl.noaa.gov/data/correlation/nina34.anom.data",
        "missing": -99.99,
        "label": "Nino 3.4 SST anomaly (NOAA PSL, 1981-2010 base)",
    },
    "dmi": {
        "url": "https://psl.noaa.gov/gcos_wgsp/Timeseries/Data/dmi.had.long.data",
        "missing": -9999.0,
        "label": "Dipole Mode Index, HadISST (NOAA PSL)",
    },
}


def _download(key: str, refresh: bool = False) -> str:
    cache = os.path.join(RAW, "climate", f"{key}.txt")
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    if refresh or not os.path.exists(cache):
        with urllib.request.urlopen(SOURCES[key]["url"], timeout=60) as resp:
            payload = resp.read().decode("utf-8", "replace")
        with open(cache, "w") as fh:
            fh.write(payload)
    return open(cache).read()


def load_index(key: str, refresh: bool = False) -> pd.Series:
    """Monthly series indexed by month-end timestamp, missing values dropped."""
    text = _download(key, refresh)
    missing = SOURCES[key]["missing"]
    rows = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 13:
            continue
        try:
            year = int(parts[0])
            values = [float(v) for v in parts[1:]]
        except ValueError:
            continue
        if not 1800 <= year <= 2100:
            continue
        for month, value in enumerate(values, start=1):
            if abs(value - missing) < 1e-6 or value <= missing + 1e-6:
                continue
            rows[pd.Timestamp(year=year, month=month, day=1)] = value
    if not rows:
        raise RuntimeError(f"could not parse {key} from {SOURCES[key]['url']}")
    return pd.Series(rows).sort_index()


@dataclass
class ClimateState:
    year: int
    nino34: float | None
    dmi: float | None
    nino34_months: str
    available: list[str]

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def season_state(year: int, season_start_month: int, indices: dict[str, pd.Series],
                 window: int = 3) -> ClimateState:
    """Predictor state as it stood just before a season opened.

    Each predictor is the mean of the `window` months ending with the month
    before the season starts - so for a June season it is the March-to-May
    mean, which is public by 1 June.
    """
    end = pd.Timestamp(year=year, month=season_start_month, day=1) - pd.offsets.MonthBegin(1)
    start = end - pd.offsets.MonthBegin(window - 1)
    out, available = {}, []
    for key, series in indices.items():
        chunk = series[(series.index >= start) & (series.index <= end)]
        if len(chunk) == window:
            out[key] = float(chunk.mean())
            available.append(key)
        else:
            out[key] = None
    months = f"{start.strftime('%b')}-{end.strftime('%b')} {end.year}"
    return ClimateState(int(year), out.get("nino34"), out.get("dmi"), months, available)


def load_all(refresh: bool = False) -> dict[str, pd.Series]:
    return {key: load_index(key, refresh) for key in SOURCES}


def state_table(years, season_start_month: int, indices: dict[str, pd.Series],
                window: int = 3) -> pd.DataFrame:
    rows = [season_state(int(y), season_start_month, indices, window).to_dict() for y in years]
    frame = pd.DataFrame(rows).set_index("year", drop=False)
    return frame
