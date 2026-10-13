"""Project paths and config loading.  Nothing in src/ hard-codes a number that
belongs in config/ (see docs/assumptions.md)."""
from __future__ import annotations

import functools
import os

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG = os.path.join(ROOT, "config")
RAW = os.path.join(ROOT, "data", "raw")
PROCESSED = os.path.join(ROOT, "data", "processed")
SITE_DATA = os.path.join(ROOT, "docs", "data")


@functools.lru_cache(maxsize=None)
def load_config(name: str) -> dict:
    with open(os.path.join(CONFIG, f"{name}.yaml")) as fh:
        return yaml.safe_load(fh)


def ensure_dirs() -> None:
    for path in (PROCESSED, SITE_DATA):
        os.makedirs(path, exist_ok=True)
