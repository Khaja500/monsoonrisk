"""Fail the scheduled build when the data has not actually moved.

A cron that commits whatever it got is worse than no cron: the page then shows
an old number under a new date.  This checks that the newest observation in
every city's series, and in the published weather.json, is recent enough to be
worth republishing.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from src.common.paths import PROCESSED, SITE_DATA, load_config


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-age-days", type=int, default=6)
    args = ap.parse_args()
    today = pd.Timestamp.utcnow().tz_localize(None).normalize()
    problems = []

    for key in load_config("cities")["cities"]:
        path = os.path.join(PROCESSED, f"{key}_daily.csv")
        frame = pd.read_csv(path, index_col=0, parse_dates=True)
        latest = frame.index.max()
        age = (today - latest).days
        print(f"{key}: latest observation {latest.date()} ({age} days old)")
        if age > args.max_age_days:
            problems.append(f"{key} is {age} days stale (limit {args.max_age_days})")

    site = os.path.join(SITE_DATA, "weather.json")
    with open(site) as fh:
        data = json.load(fh)
    for key, city in data["cities"].items():
        days = city["current_season"]["days_elapsed"]
        total = city["current_season"]["days_in_season"]
        print(f"{key}: {days} of {total} season days present")
        if days == 0 and city["current_season"]["year"] == today.year:
            in_season = pd.Timestamp(f"{today.year}-{city['window'][0]}") <= today
            if in_season:
                problems.append(f"{key} has no days for a season that has started")

    if problems:
        print("\nFRESHNESS CHECK FAILED:")
        for p in problems:
            print(" -", p)
        return 1
    print("\nfreshness ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
