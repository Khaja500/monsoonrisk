"""Module A, step 1: turn IMD gridded daily rainfall into one clean daily
series per city.

Archive years come from the IMD 0.25-degree gridded product (1901-present) read
with imdlib.  The current year is not yet published in the archive, so it is
taken from IMD's real-time gridded feed when that server responds and from NASA
POWER (MERRA-2 based, PRECTOTCORR) otherwise; either way those rows are flagged
`is_provisional = True` and the source is recorded per row, never mixed in
silently.
"""
from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..common.paths import PROCESSED, RAW, load_config

GRID_STEP = 0.25
MISSING = -99.0


@dataclass
class CellChoice:
    lat: float
    lon: float
    neighbours: list[tuple[float, float]]


def _probe_dataset(year: int):
    import imdlib

    handle = imdlib.open_data("rain", year, year, "yearwise", os.path.join(RAW, "imd"))
    return handle.get_xarray()


def choose_cell(lat: float, lon: float, probe_year: int = 2020) -> CellChoice:
    """Nearest 0.25-degree land cell to the city, plus the valid cells of the
    surrounding 3x3 block (used as the sensitivity test in spec A.2)."""
    ds = _probe_dataset(probe_year)
    lats = np.asarray(ds["lat"].values)
    lons = np.asarray(ds["lon"].values)
    cand = []
    for dla in (0, -1, 1, -2, 2):
        for dlo in (0, -1, 1, -2, 2):
            la = lats[np.abs(lats - lat).argmin()] + dla * GRID_STEP
            lo = lons[np.abs(lons - lon).argmin()] + dlo * GRID_STEP
            if la in lats and lo in lons:
                cand.append((float(la), float(lo)))
    seen, ordered = set(), []
    for c in cand:
        if c not in seen:
            seen.add(c)
            ordered.append(c)
    ordered.sort(key=lambda c: (c[0] - lat) ** 2 + (c[1] - lon) ** 2)

    valid = []
    for la, lo in ordered:
        series = ds["rain"].sel(lat=la, lon=lo).values
        series = np.where(series <= MISSING, np.nan, series)
        if np.isfinite(series).mean() > 0.95 and np.nansum(series) > 100:
            valid.append((la, lo))
    if not valid:
        raise RuntimeError(f"no valid IMD land cell near {lat}, {lon}")
    primary = valid[0]
    neighbours = [c for c in valid[:5]]
    return CellChoice(primary[0], primary[1], neighbours)


def grid_series(cell: CellChoice, start_year: int, end_year: int,
                use_neighbour_mean: bool = False) -> pd.Series:
    """Daily rainfall (mm) for one grid cell across archive years."""
    chunks = []
    for year in range(start_year, end_year + 1):
        path = os.path.join(RAW, "imd", "rain", f"{year}.grd")
        if not os.path.exists(path):
            continue
        ds = _probe_dataset(year)
        if use_neighbour_mean:
            frames = []
            for la, lo in cell.neighbours:
                v = ds["rain"].sel(lat=la, lon=lo).values
                frames.append(np.where(v <= MISSING, np.nan, v))
            values = np.nanmean(np.vstack(frames), axis=0)
        else:
            values = ds["rain"].sel(lat=cell.lat, lon=cell.lon).values
            values = np.where(values <= MISSING, np.nan, values)
        chunks.append(pd.Series(values, index=pd.DatetimeIndex(ds["time"].values)))
    if not chunks:
        raise RuntimeError("no archive years found - run scripts/download_imd.py first")
    out = pd.concat(chunks).sort_index()
    return out[~out.index.duplicated()]


def imd_realtime_series(cell: CellChoice, start: str, end: str) -> pd.Series | None:
    """IMD real-time gridded rainfall for the unpublished current year.
    Returns None if the server does not answer (it frequently does not)."""
    try:
        import imdlib

        handle = imdlib.get_real_data("rain", start, end, file_dir=os.path.join(RAW, "imd_rt"))
        ds = handle.get_xarray()
        values = ds["rain"].sel(lat=cell.lat, lon=cell.lon, method="nearest").values
        values = np.where(values <= MISSING, np.nan, values)
        return pd.Series(values, index=pd.DatetimeIndex(ds["time"].values))
    except Exception:
        return None


def power_series(lat: float, lon: float, start: str, end: str) -> pd.Series:
    """NASA POWER daily corrected precipitation - the documented fallback for
    days IMD has not published yet."""
    cache = os.path.join(RAW, "power", f"{lat}_{lon}_{start}_{end}.json")
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    if not os.path.exists(cache):
        url = ("https://power.larc.nasa.gov/api/temporal/daily/point"
               f"?parameters=PRECTOTCORR&community=AG&longitude={lon}&latitude={lat}"
               f"&start={start.replace('-', '')}&end={end.replace('-', '')}&format=JSON")
        with urllib.request.urlopen(url, timeout=120) as resp:
            payload = resp.read().decode()
        with open(cache, "w") as fh:
            fh.write(payload)
    raw = json.load(open(cache))["properties"]["parameter"]["PRECTOTCORR"]
    series = pd.Series({pd.Timestamp(k): v for k, v in raw.items()}).sort_index()
    return series.where(series > -900)


SOURCE_LABELS = {
    "imd_grid": "IMD gridded 0.25deg daily rainfall (imdlib yearwise archive)",
    "imd_rt": "IMD real-time gridded 0.25deg rainfall (provisional)",
    "nasa_power": "NASA POWER PRECTOTCORR (MERRA-2) - stands in for IMD days not yet published",
}


def load_cached_series(city_key: str) -> tuple[pd.DataFrame, pd.Series] | None:
    """Return the previously extracted daily series, if it is on disk.

    Extracting one grid cell means opening 45 yearly grids, so the result is
    cached; delete data/processed/*_daily.csv to force a rebuild.
    """
    daily_path = os.path.join(PROCESSED, f"{city_key}_daily.csv")
    ref_path = os.path.join(PROCESSED, f"{city_key}_power_reference.csv")
    if not (os.path.exists(daily_path) and os.path.exists(ref_path)):
        return None
    frame = pd.read_csv(daily_path, index_col=0, parse_dates=True)
    ref = pd.read_csv(ref_path, index_col=0, parse_dates=True)["rain_mm"]
    return frame, ref


def build_city_series(city_key: str, current_year: int, allow_realtime: bool = False,
                      rebuild: bool = False) -> pd.DataFrame:
    """Archive + provisional daily rainfall for one city, with provenance columns.

    Three source groups can appear.  `source_group` is kept because each group
    has its own bias against the station basis a contract settles on, and
    indices.py corrects each one separately.
    """
    if not rebuild:
        cached = load_cached_series(city_key)
        if cached is not None:
            return cached[0]
    cfg = load_config("cities")
    city = cfg["cities"][city_key]
    base = cfg["baseline"]
    cell = choose_cell(city["lat"], city["lon"])

    archive = grid_series(cell, base["history_start_year"], current_year - 1)
    frame = pd.DataFrame({"rain_mm": archive})
    frame["source_group"] = "imd_grid"
    frame["is_provisional"] = False

    # NASA POWER is pulled for the whole record, not just the current year: the
    # overlap with the IMD archive is what calibrates its own bias factor.
    end = pd.Timestamp.today().normalize() - pd.Timedelta(days=3)
    power = power_series(city["lat"], city["lon"],
                         f"{base['history_start_year']}-01-01", end.strftime("%Y-%m-%d"))

    live = (imd_realtime_series(cell, f"{current_year}-01-01", end.strftime("%Y-%m-%d"))
            if allow_realtime else None)
    if live is not None and live.notna().sum() > 120:
        live_frame = pd.DataFrame({"rain_mm": live.dropna()})
        live_frame["source_group"] = "imd_rt"
    else:
        live_frame = pd.DataFrame({"rain_mm": power[power.index.year >= current_year].dropna()})
        live_frame["source_group"] = "nasa_power"
    live_frame["is_provisional"] = True

    out = pd.concat([frame, live_frame])
    out = out[~out.index.duplicated(keep="first")].sort_index()
    out.index.name = "date"
    out["source"] = out["source_group"].map(SOURCE_LABELS)
    out["cell_lat"] = cell.lat
    out["cell_lon"] = cell.lon

    # Reference series used only to measure bias, never priced directly.
    ref = pd.DataFrame({"rain_mm": power})
    ref.index.name = "date"
    os.makedirs(PROCESSED, exist_ok=True)
    out.to_csv(os.path.join(PROCESSED, f"{city_key}_daily.csv"))
    ref.to_csv(os.path.join(PROCESSED, f"{city_key}_power_reference.csv"))
    return out
