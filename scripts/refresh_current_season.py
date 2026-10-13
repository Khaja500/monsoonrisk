"""Pull the current season's rainfall forward without re-reading the archive.

The 45 yearly IMD grids are not in the repository and take half an hour to
download, so the scheduled job keeps the committed daily series and only
re-fetches the provisional tail (NASA POWER, or IMD's real-time grid when it
answers) plus the climate indices.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from src.a_rainfall.climate import load_all
from src.a_rainfall.data import SOURCE_LABELS, load_cached_series, power_series
from src.common.paths import PROCESSED, load_config


def main() -> None:
    cfg = load_config("cities")
    end = pd.Timestamp.utcnow().tz_localize(None).normalize() - pd.Timedelta(days=3)
    year = end.year
    for key, city in cfg["cities"].items():
        cached = load_cached_series(key)
        if cached is None:
            raise SystemExit(f"no cached series for {key}; run scripts/extract_cities.py first")
        frame, _ref = cached
        archive = frame[frame["source_group"] == "imd_grid"]
        live = power_series(city["lat"], city["lon"], f"{year}-01-01", end.strftime("%Y-%m-%d"))
        live_frame = pd.DataFrame({"rain_mm": live.dropna()})
        live_frame["source_group"] = "nasa_power"
        live_frame["is_provisional"] = True
        live_frame["source"] = SOURCE_LABELS["nasa_power"]
        live_frame["cell_lat"] = archive["cell_lat"].iloc[0]
        live_frame["cell_lon"] = archive["cell_lon"].iloc[0]

        out = pd.concat([archive, live_frame])
        out = out[~out.index.duplicated(keep="first")].sort_index()
        out.index.name = "date"
        out.to_csv(os.path.join(PROCESSED, f"{key}_daily.csv"))

        ref_path = os.path.join(PROCESSED, f"{key}_power_reference.csv")
        ref = power_series(city["lat"], city["lon"],
                           f"{cfg['baseline']['history_start_year']}-01-01",
                           end.strftime("%Y-%m-%d"))
        pd.DataFrame({"rain_mm": ref}).rename_axis("date").to_csv(ref_path)
        print(f"{key}: {len(out)} days, latest {out.index.max().date()}", flush=True)

    indices = load_all(refresh=True)
    for name, series in indices.items():
        print(f"{name}: latest {series.index[-1].strftime('%Y-%m')}", flush=True)


if __name__ == "__main__":
    main()
