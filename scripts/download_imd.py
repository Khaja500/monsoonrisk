"""Download IMD 0.25-degree gridded daily rainfall (1901-present) via imdlib.

Files land in data/raw/imd/rain/<year>.grd and are never edited afterwards
(see data/raw/README.md for provenance).  Years are fetched in parallel
processes because imdlib itself is sequential and each year takes ~45 s.
"""
from __future__ import annotations

import os
import sys
from concurrent.futures import ProcessPoolExecutor

import imdlib

RAW = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "raw", "imd")


def fetch(year: int) -> str:
    target = os.path.join(RAW, "rain", f"{year}.grd")
    if os.path.exists(target) and os.path.getsize(target) > 1_000_000:
        return f"{year}: cached"
    try:
        imdlib.get_data("rain", year, year, fn_format="yearwise", file_dir=RAW)
        return f"{year}: ok {os.path.getsize(target)}"
    except Exception as exc:  # noqa: BLE001 - provenance matters more than the type
        return f"{year}: FAILED {exc}"


if __name__ == "__main__":
    start, end = int(sys.argv[1]), int(sys.argv[2])
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    years = list(range(start, end + 1))
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for line in pool.map(fetch, years):
            print(line, flush=True)
