from __future__ import annotations

from datetime import date
import calendar

import pandas as pd

from .constants import DAYS_ALLOWED


def build_participant_daily_attendance(
    participants_df: pd.DataFrame,
    attendance_days_col: str,
    attendance_flag_col: str,
    serial_col: str,
    name_col: str,
    day_name: str,
    attendance_date: date,
) -> pd.DataFrame:
    if participants_df.empty:
        return pd.DataFrame()
    out_rows = []
    for sid, name, days, flag in zip(
        participants_df[serial_col].tolist(),
        participants_df[name_col].tolist(),
        participants_df[attendance_days_col].tolist(),
        participants_df[attendance_flag_col].tolist(),
    ):
        expected = False
        days_list = []
        if isinstance(days, (list, tuple, set)):
            days_list = [str(d).strip() for d in days]
        else:
            s = "" if days is None else str(days)
            days_list = [p.strip() for p in s.split(",") if p.strip()]
        expected = day_name in set(days_list) if day_name in DAYS_ALLOWED else False
        active = str(flag).strip().upper() != "X"
        expected = expected and active
        out_rows.append(
            {
                "Date": attendance_date.isoformat(),
                "Serial Number": str(sid).strip() if sid is not None else "",
                "Participant Name": str(name).strip() if name is not None else "",
                "Expected": "Yes" if expected else "No",
                "Attended": "",
            }
        )
    return pd.DataFrame(out_rows)


def build_staff_daily_attendance(
    staff_df: pd.DataFrame,
    current_day_col: str,
    serial_col: str,
    first_name_col: str,
    last_name_col: str,
    scholarship_col: str,
    day_name: str,
    attendance_date: date,
) -> pd.DataFrame:
    if staff_df.empty:
        return pd.DataFrame()
    out_rows = []
    for sid, fn, ln, sch, cur_day in zip(
        staff_df[serial_col].tolist(),
        staff_df[first_name_col].tolist(),
        staff_df[last_name_col].tolist(),
        staff_df[scholarship_col].tolist(),
        staff_df[current_day_col].tolist(),
    ):
        expected = str(cur_day).strip() == day_name
        out_rows.append(
            {
                "Date": attendance_date.isoformat(),
                "Serial Number": str(sid).strip() if sid is not None else "",
                "First Name": str(fn).strip() if fn is not None else "",
                "Last Name": str(ln).strip() if ln is not None else "",
                "Scholarship": str(sch).strip() if sch is not None else "",
                "Expected": "Yes" if expected else "No",
                "Attended": "",
                "Transportation Done": "",
                "Transportation Type": "",
                "Hours": "",
            }
        )
    return pd.DataFrame(out_rows)


def summarize_participant_attendance(
    attendance_df: pd.DataFrame,
    serial_col: str,
    name_col: str,
    attended_col: str,
) -> pd.DataFrame:
    if attendance_df.empty:
        return pd.DataFrame()
    df = attendance_df.copy()
    if "Date" not in df.columns:
        return pd.DataFrame()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df[pd.notna(df["Date"])]
    df["Month"] = df["Date"].dt.strftime("%Y-%m")
    df["AttendedFlag"] = df[attended_col].map(lambda v: str(v).strip().lower() in {"yes", "true", "1", "✓"})
    grouped = (
        df[df["AttendedFlag"]]
        .groupby([serial_col, name_col, "Month"])
        .size()
        .reset_index(name="Attendances")
        .sort_values([serial_col, "Month"])
    )
    return grouped


def summarize_staff_hours(attendance_df: pd.DataFrame, serial_col: str, hours_col: str) -> pd.DataFrame:
    if attendance_df.empty:
        return pd.DataFrame()
    out = attendance_df.copy()
    totals = {}
    for sid, hrs in zip(out[serial_col].tolist(), out[hours_col].tolist()):
        key = "" if sid is None else str(sid).strip()
        if not key:
            continue
        try:
            h = float(str(hrs).strip())
        except Exception:
            h = 0.0
        totals[key] = totals.get(key, 0.0) + h
    return pd.DataFrame({"Serial Number": list(totals.keys()), "Total Hours": list(totals.values())})


def summarize_participant_attendance_yearly(
    attendance_df: pd.DataFrame,
    participants_df: pd.DataFrame,
    year: int,
    participants_serial_col: str,
    participants_name_col: str,
    participants_last_name_col: str,
    participants_attendance_col: str,
    attendance_serial_col: str,
    attended_col: str,
) -> pd.DataFrame:
    month_cols = [calendar.month_name[m] for m in range(1, date.today().month + 1)]
    base_cols = ["Serial Number", "Participant Name"] + month_cols

    if participants_df.empty:
        return pd.DataFrame(columns=base_cols)

    p = participants_df.copy()
    for c in [participants_serial_col, participants_name_col, participants_attendance_col]:
        if c not in p.columns:
            return pd.DataFrame(columns=base_cols)
    if participants_last_name_col not in p.columns:
        p[participants_last_name_col] = ""

    def _is_active(v: object) -> bool:
        if isinstance(v, bool):
            return v
        s = "" if v is None else str(v).strip().lower()
        return s in {"✓", "true", "1", "yes", "y"}

    active = p[p[participants_attendance_col].map(_is_active)].copy()
    if active.empty:
        return pd.DataFrame(columns=base_cols)

    counts: dict[tuple[str, int], int] = {}
    if not attendance_df.empty and "Date" in attendance_df.columns and attendance_serial_col in attendance_df.columns:
        att = attendance_df.copy()
        att["Date"] = pd.to_datetime(att["Date"], errors="coerce")
        att = att[pd.notna(att["Date"])]
        att = att[att["Date"].dt.year == year]

        def _attended(v: object) -> bool:
            s = "" if v is None else str(v).strip().lower()
            return s in {"yes", "true", "1", "✓"}

        if attended_col in att.columns:
            att = att[att[attended_col].map(_attended)]
            for sid, dt in zip(att[attendance_serial_col].tolist(), att["Date"].tolist()):
                sid_key = "" if sid is None else str(sid).strip()
                if not sid_key:
                    continue
                key = (sid_key, int(dt.month))
                counts[key] = counts.get(key, 0) + 1

    rows = []
    for _, row in active.iterrows():
        sid = "" if row.get(participants_serial_col) is None else str(row.get(participants_serial_col)).strip()
        first = "" if row.get(participants_name_col) is None else str(row.get(participants_name_col)).strip()
        last = "" if row.get(participants_last_name_col) is None else str(row.get(participants_last_name_col)).strip()
        name = f"{first} {last}".strip()
        row_out = {"Serial Number": sid, "Participant Name": name}
        for m in range(1, date.today().month + 1):
            row_out[calendar.month_name[m]] = str(counts.get((sid, m), 0))
        rows.append(row_out)

    return pd.DataFrame(rows, columns=base_cols)
