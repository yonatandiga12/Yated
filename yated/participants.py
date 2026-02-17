from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable

import pandas as pd

from .constants import DAYS_ALLOWED, DAYS_OPTIONS, PAYMENT_PER_DAY, MORNING_FRAMEWORK_ALERT


@dataclass
class MediaConsentState:
    df: pd.DataFrame
    needs_attention: list[bool]


def _parse_birthdate_to_date(v: object) -> date | None:
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() == "nan":
        return None

    dt = pd.to_datetime(s, errors="coerce", dayfirst=True)
    if pd.notna(dt):
        try:
            return dt.date()
        except Exception:
            pass

    try:
        f = float(s)
        dt2 = pd.to_datetime(f, unit="D", origin="1899-12-30", errors="coerce")
        if pd.notna(dt2):
            return dt2.date()
    except Exception:
        pass

    return None


def _calculate_age_years(born: date, today: date) -> int:
    years = today.year - born.year
    if (today.month, today.day) < (born.month, born.day):
        years -= 1
    return max(0, years)


def compute_age_column(df: pd.DataFrame, birthdate_col: str, age_col: str) -> pd.DataFrame:
    if birthdate_col not in df.columns:
        return df
    out = df.copy()
    today = date.today()
    ages: list[str] = []
    for v in out[birthdate_col].tolist():
        born = _parse_birthdate_to_date(v)
        if born is None:
            ages.append("")
        else:
            ages.append(str(_calculate_age_years(born, today)))
    if age_col in out.columns:
        out[age_col] = ages
    else:
        out.insert(len(out.columns), age_col, ages)
    return out


def _shift_month(dt: date, months: int) -> date:
    year = dt.year + (dt.month - 1 + months) // 12
    month = (dt.month - 1 + months) % 12 + 1
    day = min(dt.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                       31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return date(year, month, day)


def needs_morning_framework_alert(born: date | None, today: date | None = None) -> bool:
    if born is None:
        return False
    today = today or date.today()
    twenty_first = date(born.year + 21, born.month, born.day)
    one_month_before = _shift_month(twenty_first, -1)
    return today >= one_month_before


def normalize_days_for_editor(df: pd.DataFrame, days_col: str) -> pd.DataFrame:
    if days_col not in df.columns:
        return df
    out = df.copy()

    def _to_list(v: object) -> list[str]:
        if v is None:
            return []
        if isinstance(v, list):
            parts = [str(p).strip() for p in v]
        else:
            s = str(v).strip()
            if not s or s.lower() == "nan":
                return []
            parts = [p.strip() for p in s.split(",")]
        parts = [p for p in parts if p in DAYS_ALLOWED]
        seen = set()
        out_parts = []
        for p in parts:
            if p not in seen:
                seen.add(p)
                out_parts.append(p)
        return out_parts

    out[days_col] = out[days_col].map(_to_list)
    return out


def normalize_days_for_save(df: pd.DataFrame, days_col: str) -> pd.DataFrame:
    if days_col not in df.columns:
        return df
    out = df.copy()

    def _to_str(v: object) -> str:
        if v is None:
            return ""
        if isinstance(v, (list, tuple, set)):
            parts = [str(p).strip() for p in v]
            parts = [p for p in parts if p in DAYS_ALLOWED]
            ordered = [d for d in DAYS_OPTIONS if d in set(parts)]
            return ", ".join(ordered)
        s = str(v).strip()
        if not s or s.lower() == "nan":
            return ""
        return s

    out[days_col] = out[days_col].map(_to_str)
    return out


def _count_allowed_days(text: object) -> int:
    if text is None:
        return 0
    if isinstance(text, (list, tuple, set)):
        parts = [str(p).strip() for p in text]
        parts = [p for p in parts if p]
        return len({p for p in parts if p in DAYS_ALLOWED})

    s = str(text).strip()
    if not s or s.lower() == "nan":
        return 0
    parts = [p.strip() for p in s.split(",")]
    parts = [p for p in parts if p]
    return len({p for p in parts if p in DAYS_ALLOWED})


def compute_required_payment(df: pd.DataFrame, days_col: str, payment_col: str) -> pd.DataFrame:
    if days_col not in df.columns:
        return df
    out = df.copy()
    payments = [str(_count_allowed_days(v) * PAYMENT_PER_DAY) for v in out[days_col].tolist()]
    if payment_col in out.columns:
        out[payment_col] = payments
    else:
        out.insert(len(out.columns), payment_col, payments)
    return out


def normalize_media_consent_for_editor(
    df: pd.DataFrame, consent_col: str, year_col: str, current_year: int
) -> MediaConsentState:
    out = df.copy()
    needs_attention: list[bool] = []

    def _to_bool(v: object, y: object) -> bool:
        s = "" if v is None else str(v).strip()
        consented = s == "✓"
        try:
            y_int = int(str(y).strip())
        except Exception:
            y_int = None
        current = consented and y_int == current_year
        needs_attention.append(not current)
        return current

    if consent_col not in out.columns:
        return MediaConsentState(out, needs_attention)

    years = out[year_col] if year_col in out.columns else [""] * len(out)
    out[consent_col] = [
        _to_bool(v, y) for v, y in zip(out[consent_col].tolist(), list(years))
    ]
    return MediaConsentState(out, needs_attention)


def normalize_media_consent_for_save(
    df: pd.DataFrame, consent_col: str, year_col: str, current_year: int
) -> pd.DataFrame:
    out = df.copy()
    if consent_col not in out.columns:
        return out

    def _consent_to_sheet(v: object) -> str:
        return "✓" if bool(v) else ""

    out[consent_col] = out[consent_col].map(_consent_to_sheet)
    if year_col in out.columns:
        out[year_col] = out[consent_col].map(lambda v: str(current_year) if v == "✓" else "")
    return out


def normalize_attendance_for_editor(df: pd.DataFrame, attendance_col: str) -> pd.DataFrame:
    if attendance_col not in df.columns:
        return df
    out = df.copy()

    def _to_bool(v: object) -> bool:
        if isinstance(v, bool):
            return v
        s = "" if v is None else str(v).strip().upper()
        return s == "✓"

    out[attendance_col] = out[attendance_col].map(_to_bool)
    return out


def normalize_attendance_for_save(df: pd.DataFrame, attendance_col: str) -> pd.DataFrame:
    if attendance_col not in df.columns:
        return df
    out = df.copy()
    out[attendance_col] = out[attendance_col].map(lambda v: "✓" if bool(v) else "X")
    return out


def move_absent_to_bottom(df: pd.DataFrame, attendance_col: str, name_cols: Iterable[str]) -> pd.DataFrame:
    if attendance_col not in df.columns:
        return df
    out = df.copy()
    key = out[attendance_col].astype(str).map(lambda v: str(v).strip().upper())
    out["_sort_absent"] = (key == "X").astype(int)
    sort_cols = ["_sort_absent"] + [c for c in name_cols if c in out.columns]
    out = out.sort_values(sort_cols, kind="mergesort")
    out = out.drop(columns=["_sort_absent"])
    return out


def _looks_int(s: str) -> bool:
    s2 = s.strip()
    if not s2:
        return False
    try:
        int(s2)
        return True
    except Exception:
        return False


def autofill_serial_numbers(df: pd.DataFrame, id_col: str) -> pd.DataFrame:
    if id_col not in df.columns:
        return df

    out = df.copy()
    series = out[id_col].astype(str)
    blank_mask = series.str.strip().eq("") | series.str.strip().str.lower().eq("nan")

    existing_ints: list[int] = []
    for v in series[~blank_mask].tolist():
        if _looks_int(v):
            existing_ints.append(int(v.strip()))

    next_id = (max(existing_ints) + 1) if existing_ints else 1

    for idx in out.index.tolist():
        v = str(out.at[idx, id_col])
        if v.strip() == "" or v.strip().lower() == "nan":
            out.at[idx, id_col] = str(next_id)
            next_id += 1

    return out


def sanitize_df_for_sheet(df: pd.DataFrame) -> pd.DataFrame:
    df2 = df.copy()
    df2.columns = [str(c).strip() for c in df2.columns]
    df2 = df2.where(pd.notnull(df2), "")
    for c in df2.columns:
        df2[c] = df2[c].map(lambda v: "" if v is None else str(v))
    return df2


def apply_participant_rules(
    df: pd.DataFrame,
    id_col: str,
    birthdate_col: str,
    age_col: str,
    days_col: str,
    payment_col: str,
    attendance_col: str,
    consent_col: str,
    consent_year_col: str,
    current_year: int,
    name_cols: Iterable[str],
) -> pd.DataFrame:
    out = normalize_days_for_save(df, days_col=days_col)
    out = normalize_attendance_for_save(out, attendance_col=attendance_col)
    out = normalize_media_consent_for_save(out, consent_col, consent_year_col, current_year)
    out = sanitize_df_for_sheet(out)
    out = autofill_serial_numbers(out, id_col=id_col)
    out = compute_age_column(out, birthdate_col=birthdate_col, age_col=age_col)
    out = compute_required_payment(out, days_col=days_col, payment_col=payment_col)
    out = move_absent_to_bottom(out, attendance_col=attendance_col, name_cols=name_cols)
    return out


def build_morning_framework_alert_mask(
    df: pd.DataFrame,
    birthdate_col: str,
    framework_col: str,
    today: date | None = None,
) -> list[bool]:
    today = today or date.today()
    if birthdate_col not in df.columns or framework_col not in df.columns:
        return [False] * len(df)
    mask = []
    for b, f in zip(df[birthdate_col].tolist(), df[framework_col].tolist()):
        born = _parse_birthdate_to_date(b)
        fw = "" if f is None else str(f).strip()
        alert = fw in MORNING_FRAMEWORK_ALERT and needs_morning_framework_alert(born, today)
        mask.append(alert)
    return mask
