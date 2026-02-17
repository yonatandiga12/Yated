from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from . import constants as yated_constants

TRANSPORTATION_OPTIONS = getattr(
    yated_constants,
    "TRANSPORTATION_OPTIONS",
    ["Ofakim", "Beer Sheva", "Haloch", "Hazor"],
)


@dataclass
class PoliceClearanceState:
    df: pd.DataFrame
    needs_attention: list[bool]


def normalize_police_clearance_for_editor(
    df: pd.DataFrame, gender_col: str, clearance_col: str
) -> PoliceClearanceState:
    out = df.copy()
    needs_attention: list[bool] = []

    if clearance_col not in out.columns:
        return PoliceClearanceState(out, needs_attention)

    def _to_bool(g: object, v: object) -> bool:
        gender = "" if g is None else str(g).strip().lower()
        is_male = gender in {"male", "m"}
        checked = bool(v) if isinstance(v, bool) else str(v).strip() == "✓"
        needs_attention.append(is_male and not checked)
        return checked

    out[clearance_col] = [
        _to_bool(g, v) for g, v in zip(out[gender_col].tolist(), out[clearance_col].tolist())
    ]
    return PoliceClearanceState(out, needs_attention)


def normalize_police_clearance_for_save(df: pd.DataFrame, clearance_col: str) -> pd.DataFrame:
    if clearance_col not in df.columns:
        return df
    out = df.copy()
    out[clearance_col] = out[clearance_col].map(lambda v: "✓" if bool(v) else "")
    return out


def compute_hourly_totals(attendance_df: pd.DataFrame, serial_col: str, hours_col: str) -> dict[str, float]:
    if attendance_df.empty or serial_col not in attendance_df.columns or hours_col not in attendance_df.columns:
        return {}
    totals: dict[str, float] = {}
    for sid, hrs in zip(attendance_df[serial_col].tolist(), attendance_df[hours_col].tolist()):
        key = "" if sid is None else str(sid).strip()
        if not key:
            continue
        try:
            h = float(str(hrs).strip())
        except Exception:
            h = 0.0
        totals[key] = totals.get(key, 0.0) + h
    return totals


def apply_hourly_totals(
    staff_df: pd.DataFrame,
    serial_col: str,
    hourly_total_col: str,
    totals: dict[str, float],
) -> pd.DataFrame:
    if staff_df.empty or serial_col not in staff_df.columns:
        return staff_df
    out = staff_df.copy()
    totals_list = []
    for sid in out[serial_col].tolist():
        key = "" if sid is None else str(sid).strip()
        totals_list.append(str(round(totals.get(key, 0.0), 2)) if key else "")
    if hourly_total_col in out.columns:
        out[hourly_total_col] = totals_list
    else:
        out.insert(len(out.columns), hourly_total_col, totals_list)
    return out


def compute_remaining_hours(df: pd.DataFrame, annual_col: str, total_col: str, remaining_col: str) -> pd.DataFrame:
    if annual_col not in df.columns or total_col not in df.columns:
        return df
    out = df.copy()
    remaining: list[str] = []
    for annual, total in zip(out[annual_col].tolist(), out[total_col].tolist()):
        try:
            a = float(str(annual).strip())
        except Exception:
            a = 0.0
        try:
            t = float(str(total).strip())
        except Exception:
            t = 0.0
        remaining.append(str(round(a - t, 2)))
    if remaining_col in out.columns:
        out[remaining_col] = remaining
    else:
        out.insert(len(out.columns), remaining_col, remaining)
    return out


def build_staff_backup_df(
    staff_df: pd.DataFrame,
    year: int,
    hours_debt_col: str,
    remove_cols: list[str],
    year_col: str,
) -> pd.DataFrame:
    if staff_df.empty:
        return staff_df.copy()
    out = staff_df.copy()
    for c in remove_cols:
        if c in out.columns:
            out = out.drop(columns=[c])
    out[year_col] = str(year)
    if hours_debt_col not in out.columns:
        out[hours_debt_col] = ""
    return out


def summarize_staff_by_scholarship(df: pd.DataFrame, scholarship_col: str, year_col: str) -> pd.DataFrame:
    if df.empty or scholarship_col not in df.columns or year_col not in df.columns:
        return pd.DataFrame()
    summary = (
        df.groupby([year_col, scholarship_col])
        .size()
        .reset_index(name="Count")
        .sort_values([year_col, scholarship_col])
    )
    totals = df.groupby([year_col]).size().reset_index(name="Total Instructors")
    return summary.merge(totals, on=year_col, how="left")


def should_rollover(last_year: int | None, today: date | None = None) -> bool:
    today = today or date.today()
    if today.month < 9 or (today.month == 9 and today.day < 1):
        return False
    if last_year is None:
        return True
    return today.year > last_year


def _normalize_scholarship(value: object) -> str:
    return "" if value is None else str(value).strip().lower()


def derive_weekly_hours_from_scholarship(scholarship: object) -> str:
    normalized = _normalize_scholarship(scholarship)
    if normalized in {"keren moshe", "perach", "telem"}:
        return "4"
    if normalized in {"nakaz", "volunteer"}:
        return "2"
    return ""


def derive_transportation_from_scholarship(scholarship: object, current_transportation: object) -> str:
    normalized = _normalize_scholarship(scholarship)
    if normalized in {"nakaz", "volunteer"}:
        return "X"
    current = "" if current_transportation is None else str(current_transportation).strip()
    allowed = set(TRANSPORTATION_OPTIONS)
    return current if current in allowed else ""


def apply_staff_details_rules(
    df: pd.DataFrame,
    scholarship_col: str,
    transportation_col: str,
    weekly_hours_col: str,
) -> pd.DataFrame:
    out = df.copy()
    if scholarship_col not in out.columns:
        return out

    if transportation_col in out.columns:
        out[transportation_col] = [
            derive_transportation_from_scholarship(s, t)
            for s, t in zip(out[scholarship_col].tolist(), out[transportation_col].tolist())
        ]

    if weekly_hours_col in out.columns:
        out[weekly_hours_col] = [derive_weekly_hours_from_scholarship(s) for s in out[scholarship_col].tolist()]

    return out
