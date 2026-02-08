from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from .constants import MONTHS_NOV_JUL


@dataclass
class BillingTable:
    df: pd.DataFrame
    partial_mask: dict[tuple[int, str], bool]


def _month_name_from_date_str(s: str) -> str | None:
    try:
        dt = pd.to_datetime(s, errors="coerce")
    except Exception:
        dt = None
    if dt is None or pd.isna(dt):
        return None
    return dt.strftime("%B")


def build_billing_table(
    participants_df: pd.DataFrame,
    payments_df: pd.DataFrame,
    serial_col: str,
    name_col: str,
    required_col: str,
    payment_serial_col: str,
    payment_amount_col: str,
    payment_date_col: str,
    payment_month_col: str,
) -> BillingTable:
    if participants_df.empty:
        return BillingTable(pd.DataFrame(), {})

    pay = payments_df.copy() if not payments_df.empty else pd.DataFrame()
    if not pay.empty and payment_month_col not in pay.columns:
        pay[payment_month_col] = pay[payment_date_col].map(lambda v: _month_name_from_date_str(str(v)))

    rows = []
    partial_mask: dict[tuple[int, str], bool] = {}

    for idx, row in participants_df.iterrows():
        sid = str(row.get(serial_col, "")).strip()
        name = str(row.get(name_col, "")).strip()
        try:
            required = float(str(row.get(required_col, "0")).strip())
        except Exception:
            required = 0.0

        month_values = {m: 0.0 for m in MONTHS_NOV_JUL}
        if not pay.empty and sid:
            p_rows = pay[pay[payment_serial_col].astype(str).str.strip() == sid]
            for _, prow in p_rows.iterrows():
                try:
                    amt = float(str(prow.get(payment_amount_col, "0")).strip())
                except Exception:
                    amt = 0.0
                month = str(prow.get(payment_month_col, "")).strip()
                if month in month_values:
                    month_values[month] += amt

        row_out = {"Serial Number": sid, "Participant Name": name}
        for m in MONTHS_NOV_JUL:
            row_out[m] = str(round(month_values[m], 2)) if month_values[m] else ""
            if required > 0 and 0 < month_values[m] < required:
                partial_mask[(len(rows), m)] = True
        total_paid = sum(month_values.values())
        required_total = required * len(MONTHS_NOV_JUL)
        row_out["Total Paid"] = str(round(total_paid, 2))
        row_out["Balance"] = str(round(required_total - total_paid, 2))
        rows.append(row_out)

    df = pd.DataFrame(rows)
    return BillingTable(df, partial_mask)
