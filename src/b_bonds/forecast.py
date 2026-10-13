"""A seasonal forecast with actual content, and an honest test of whether it has any.

The futures fair value is `spot + (factor - 1) * remaining normal + ...`.  With
`factor` set to the centre of IMD's categorical outlook the term is identically
zero, so the model can never disagree with spot.  This module replaces that with
a regression of the seasonal total (as a ratio to the long-period average) on
climate state known before the season opens, and then refuses to use it unless
it beats climatology out of sample.

Five variants are fitted and scored the same way:

    climatology   predict the training mean - the thing to beat
    trend         a linear year term only
    enso          Nino 3.4 in the three months before the season
    enso_iod      Nino 3.4 and the Dipole Mode Index
    enso_trend    Nino 3.4 and a year term

Scoring is a strict expanding window: the model for season `y` is fitted on
seasons before `y` and never sees its own answer.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

VARIANTS = {
    "climatology": [],
    "trend": ["year_c"],
    "enso": ["nino34"],
    "enso_iod": ["nino34", "dmi"],
    "enso_trend": ["nino34", "year_c"],
}
MIN_TRAIN = 20
YEAR_CENTRE = 2005.5          # centre of the 1991-2020 baseline


def _design(frame: pd.DataFrame, cols: list[str]) -> np.ndarray:
    n = len(frame)
    out = [np.ones(n)]
    for c in cols:
        out.append(frame[c].to_numpy(dtype=float))
    return np.column_stack(out)


def _fit_ols(frame: pd.DataFrame, cols: list[str], target: str = "ratio"):
    x = _design(frame, cols)
    y = frame[target].to_numpy(dtype=float)
    coef, *_ = np.linalg.lstsq(x, y, rcond=None)
    resid = y - x @ coef
    ss_res = float(resid @ resid)
    ss_tot = float(((y - y.mean()) ** 2).sum())
    return coef, (1 - ss_res / ss_tot if ss_tot > 0 else 0.0)


@dataclass
class VariantSkill:
    name: str
    predictors: list[str]
    n_scored: int
    mae: float
    rmse: float
    bias: float
    skill_vs_climatology: float        # fraction of RMSE removed; negative is worse
    coefficients: dict = field(default_factory=dict)
    r2_in_sample: float = 0.0
    usable: bool = True

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class ClimateForecast:
    city: str
    anchor_mm: float
    table: pd.DataFrame                 # year, ratio, predictors
    skills: dict[str, VariantSkill]
    selected: str
    predictions: list[dict]

    @property
    def best(self) -> VariantSkill:
        return self.skills[self.selected]

    def factor(self, state: dict, year: int, variant: str | None = None) -> dict:
        """Predicted seasonal total as a fraction of the long-period average."""
        name = variant or self.selected
        cols = VARIANTS[name]
        rows = self.table.dropna(subset=["ratio"] + cols) if cols else self.table.dropna(subset=["ratio"])
        if name == "climatology" or len(rows) < MIN_TRAIN:
            return {"variant": "climatology", "factor": float(rows["ratio"].mean()),
                    "inputs": {}, "reason": "climatology"}
        missing = [c for c in cols if c != "year_c" and state.get(c) is None]
        if missing:
            return {"variant": "climatology", "factor": float(rows["ratio"].mean()),
                    "inputs": {}, "reason": f"predictor not published yet: {', '.join(missing)}"}
        coef, _ = _fit_ols(rows, cols)
        values = {c: (year - YEAR_CENTRE if c == "year_c" else float(state[c])) for c in cols}
        factor = float(coef[0] + sum(coef[i + 1] * values[c] for i, c in enumerate(cols)))
        return {"variant": name, "factor": factor, "inputs": values,
                "coefficients": {"intercept": float(coef[0]),
                                 **{c: float(coef[i + 1]) for i, c in enumerate(cols)}},
                "reason": "fitted"}

    def to_dict(self) -> dict:
        return {
            "city": self.city,
            "selected": self.selected,
            "skills": {k: v.to_dict() for k, v in self.skills.items()},
            "predictions": self.predictions,
            "rows": [
                {"year": int(r.year), "ratio": float(r.ratio),
                 "nino34": None if pd.isna(r.nino34) else float(r.nino34),
                 "dmi": None if pd.isna(r.dmi) else float(r.dmi),
                 "total_mm": float(r.total_mm)}
                for r in self.table.itertuples()],
        }


def _frame_from(index_table: pd.DataFrame, climate_table: pd.DataFrame,
                anchor_mm: float) -> pd.DataFrame:
    rows = index_table[index_table["complete"] & ~index_table["provisional"]].copy()
    frame = pd.DataFrame({
        "year": rows["year"].to_numpy(dtype=int),
        "total_mm": rows["SEAS_TOTAL"].to_numpy(dtype=float),
    })
    frame["ratio"] = frame["total_mm"] / anchor_mm
    frame["year_c"] = frame["year"] - YEAR_CENTRE
    climate = climate_table.set_index("year")
    frame["nino34"] = [climate["nino34"].get(y, np.nan) for y in frame["year"]]
    frame["dmi"] = [climate["dmi"].get(y, np.nan) for y in frame["year"]]
    return frame.set_index("year", drop=False)


def walk_forward(index_table: pd.DataFrame, climate_table: pd.DataFrame, anchor_mm: float,
                 state_lookup, start_year: int, end_year: int,
                 min_train: int = MIN_TRAIN) -> list[dict]:
    """The forecast as it could actually have been made, year by year.

    For season `y` the variant is *selected* and fitted on seasons before `y`,
    so neither the coefficients nor the choice of model has seen the answer.
    Years without enough history fall back to climatology.
    """
    frame = _frame_from(index_table, climate_table, anchor_mm)
    out = []
    for year in range(start_year, end_year + 1):
        past = index_table[index_table["year"] < year]
        row = frame[frame["year"] == year]
        prior = frame[frame["year"] < year]
        if len(prior) < min_train:
            factor, variant, reason = (float(prior["ratio"].mean()) if len(prior) else 1.0,
                                       "climatology", "not enough history")
        else:
            sub = build_from_frame(prior, anchor_mm, min_train)
            state = state_lookup(year)
            picked = sub.factor(state, year)
            factor, variant, reason = picked["factor"], picked["variant"], picked["reason"]
        entry = {"year": int(year), "factor": float(factor), "variant": variant,
                 "reason": reason, "predicted_mm": float(factor * anchor_mm)}
        if len(row):
            entry["actual_mm"] = float(row["total_mm"].iloc[0])
            entry["actual_ratio"] = float(row["ratio"].iloc[0])
        out.append(entry)
    return out


def build(city_key: str, index_table: pd.DataFrame, climate_table: pd.DataFrame,
          anchor_mm: float, min_train: int = MIN_TRAIN) -> ClimateForecast:
    """Fit every variant, score them out of sample, and pick one."""
    frame = _frame_from(index_table, climate_table, anchor_mm)
    return build_from_frame(frame, anchor_mm, min_train, city_key)


def build_from_frame(frame: pd.DataFrame, anchor_mm: float, min_train: int = MIN_TRAIN,
                     city_key: str = "") -> ClimateForecast:
    scored: dict[str, list[tuple[int, float, float]]] = {k: [] for k in VARIANTS}
    for year in frame["year"]:
        train_all = frame[frame["year"] < year]
        if len(train_all) < min_train:
            continue
        actual = float(frame.loc[year, "ratio"])
        for name, cols in VARIANTS.items():
            train = train_all.dropna(subset=["ratio"] + cols)
            if len(train) < min_train:
                continue
            target = frame.loc[[year]]
            if cols and target[cols].isna().any(axis=None):
                continue
            if not cols:
                pred = float(train["ratio"].mean())
            else:
                coef, _ = _fit_ols(train, cols)
                pred = float(_design(target, cols)[0] @ coef)
            scored[name].append((int(year), pred, actual))

    base = scored["climatology"]
    base_years = {y for y, _, _ in base}
    base_rmse = float(np.sqrt(np.mean([(p - a) ** 2 for _, p, a in base]))) if base else np.nan

    skills = {}
    for name, cols in VARIANTS.items():
        pts = [t for t in scored[name] if t[0] in base_years]      # compare on common years
        if not pts:
            skills[name] = VariantSkill(name, cols, 0, np.nan, np.nan, np.nan, np.nan,
                                        usable=False)
            continue
        err = np.array([p - a for _, p, a in pts])
        rmse = float(np.sqrt(np.mean(err ** 2)))
        fitted = frame.dropna(subset=["ratio"] + cols)
        coef, r2 = _fit_ols(fitted, cols) if cols else (np.array([fitted["ratio"].mean()]), 0.0)
        skills[name] = VariantSkill(
            name=name, predictors=cols, n_scored=len(pts), mae=float(np.abs(err).mean()),
            rmse=rmse, bias=float(err.mean()),
            skill_vs_climatology=float(1 - rmse / base_rmse) if base_rmse == base_rmse else np.nan,
            coefficients={"intercept": float(coef[0]),
                          **{c: float(coef[i + 1]) for i, c in enumerate(cols)}},
            r2_in_sample=float(r2), usable=True)

    # Pick the best out-of-sample variant, but only if it actually beats
    # climatology; ties and anything worse fall back to climatology.
    ranked = sorted((s for s in skills.values() if s.usable and s.n_scored >= 10),
                    key=lambda s: s.rmse)
    selected = ranked[0].name if ranked and ranked[0].rmse < base_rmse else "climatology"

    predictions = [{"year": int(y), "predicted_ratio": float(p), "actual_ratio": float(a),
                    "predicted_mm": float(p * anchor_mm), "actual_mm": float(a * anchor_mm)}
                   for y, p, a in scored[selected]]
    return ClimateForecast(city_key, anchor_mm, frame, skills, selected, predictions)
