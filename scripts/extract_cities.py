"""Extract one daily series per city from the downloaded IMD grids.

Slow (each city opens 45 yearly grids), so it writes data/processed/*_daily.csv
and every later step reads the cache.
"""
import sys, time, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.a_rainfall.data import build_city_series
from src.common.paths import load_config

if __name__ == "__main__":
    allow_rt = "--realtime" in sys.argv
    for key in load_config("cities")["cities"]:
        t = time.time()
        frame = build_city_series(key, 2026, allow_realtime=allow_rt, rebuild=True)
        prov = frame["is_provisional"].sum()
        print(f"{key}: {len(frame)} days, {prov} provisional, "
              f"cell {frame['cell_lat'].iloc[0]}/{frame['cell_lon'].iloc[0]}, "
              f"{round(time.time() - t, 1)}s", flush=True)
