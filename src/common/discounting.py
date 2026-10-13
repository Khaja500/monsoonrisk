"""Continuously compounded discounting.  Rates are decimals, time in years."""
from __future__ import annotations

import numpy as np


def discount_factor(rate: float, years: float) -> float:
    return float(np.exp(-rate * years))


def annual_factors(rate: float, tenor: int) -> np.ndarray:
    """Discount factors for cash flows at the end of years 1..tenor."""
    return np.exp(-rate * np.arange(1, tenor + 1, dtype=float))
