import json

import re
from datetime import date

import pandas as pd
import streamlit as st

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build


DEFAULT_SPREADSHEET_ID = "19261I9RJbS0Cnar6Ex0nnWa_gZqb3lGdM7L-gfv_gWs"
DEFAULT_ID_COLUMN_NAME = "מספר סידורי"

# Note: UI is now standard LTR, and columns are shown "as-is" (sheet order).

MORNING_FRAMEWORK_OPTIONS = ["יסודות", "שחר", "דקלים", "אילנות", "מע'ש", "מרכז יותם"]
ARRIVAL_OPTIONS = ["מגיע", "לא מגיע"]
ARRIVAL_NOT_COMING_VALUE = "לא מגיע"

EXPOSURE_COL_NAME = "אישור חשיפה"
EXPOSURE_YES_VALUE = "יש"
EXPOSURE_NO_VALUE = "אין"

DAYS_OPTIONS = ["שני", "שלישי", "רביעי"]
DAYS_ALLOWED = set(DAYS_OPTIONS)
PAYMENT_PER_DAY = 80


SCOPES = [
    # Drive scope isn't required if you only use a known spreadsheetId,
    # but keeping it read-only is useful if you later add file listing.
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
]


def get_credentials() -> Credentials:
    """
    Expects Streamlit Secrets in ONE of these formats:

    Option A (recommended): TOML table (key-by-key)
      [gcp_service_account]
      type = "service_account"
      project_id = "..."
      private_key_id = "..."
      private_key = "-----BEGIN PRIVATE KEY-----\\n...\\n-----END PRIVATE KEY-----\\n"
      client_email = "....iam.gserviceaccount.com"
      client_id = "..."
      auth_uri = "https://accounts.google.com/o/oauth2/auth"
      token_uri = "https://oauth2.googleapis.com/token"
      auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
      client_x509_cert_url = "..."

    Option B (easiest): paste the ENTIRE downloaded JSON key as a TOML multiline string
      gcp_service_account_json = '''{ ... full JSON ... }'''
    """
    sa_info = st.secrets.get("gcp_service_account")
    if sa_info:
        return Credentials.from_service_account_info(dict(sa_info), scopes=SCOPES)

    sa_json = st.secrets.get("gcp_service_account_json")
    if sa_json:
        if isinstance(sa_json, str):
            sa_dict = json.loads(sa_json)
        else:
            sa_dict = dict(sa_json)
        return Credentials.from_service_account_info(sa_dict, scopes=SCOPES)

    raise RuntimeError(
        "Missing Google credentials in Streamlit Secrets.\n\n"
        "Add EITHER:\n"
        "- [gcp_service_account] (TOML table)\n"
        "OR\n"
        "- gcp_service_account_json = '''{ ... }''' (raw JSON wrapped in TOML)\n\n"
        "Streamlit Cloud → App → Settings → Secrets."
    )


@st.cache_data(show_spinner=False, ttl=30)
def get_spreadsheet_metadata(_creds: Credentials, spreadsheet_id: str) -> dict:
    sheets = build("sheets", "v4", credentials=_creds, cache_discovery=False)
    return sheets.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()


def _a1_range_for_all(sheet_name: str) -> str:
    # "Sheet1" without range returns the whole used grid in Sheets API reads
    return f"'{sheet_name}'"


def _normalize_headers(headers: list[str], width: int) -> list[str]:
    headers = [h.strip() if isinstance(h, str) else "" for h in headers]
    headers = headers[:width] + [""] * max(0, width - len(headers))
    # Make headers unique / non-empty for pandas
    out = []
    seen = {}
    for i, h in enumerate(headers):
        base = h if h else f"col_{i+1}"
        n = seen.get(base, 0)
        seen[base] = n + 1
        out.append(base if n == 0 else f"{base}_{n+1}")
    return out


@st.cache_data(show_spinner=False, ttl=30)
def read_sheet_as_df(_creds: Credentials, spreadsheet_id: str, worksheet_name: str) -> pd.DataFrame:
    sheets = build("sheets", "v4", credentials=_creds, cache_discovery=False)

    values_resp = sheets.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range=_a1_range_for_all(worksheet_name)
    ).execute()
    values = values_resp.get("values", [])
    if not values:
        return pd.DataFrame()

    width = max(len(r) for r in values)
    headers = _normalize_headers(values[0], width)
    rows = [r + [""] * (width - len(r)) for r in values[1:]]
    return pd.DataFrame(rows, columns=headers)


def _col_num_to_a1(col_num_1_based: int) -> str:
    # 1 -> A, 26 -> Z, 27 -> AA, ...
    if col_num_1_based <= 0:
        raise ValueError("col_num_1_based must be >= 1")
    s = ""
    n = col_num_1_based
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def append_row(creds: Credentials, spreadsheet_id: str, worksheet_name: str, row_values: list[str]) -> None:
    """
    Writes the new row starting from column A to avoid "shifting" into new columns.
    """
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)

    end_col = _col_num_to_a1(max(1, len(row_values)))
    read_range = f"'{worksheet_name}'!A1:{end_col}"
    existing = (
        sheets.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=read_range)
        .execute()
    )
    existing_values = existing.get("values", [])
    next_row = len(existing_values) + 1  # 1-based

    write_range = f"'{worksheet_name}'!A{next_row}:{end_col}{next_row}"
    sheets.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=write_range,
        valueInputOption="USER_ENTERED",
        body={"values": [row_values]},
    ).execute()


def list_worksheet_titles(meta: dict) -> list[str]:
    return [s["properties"]["title"] for s in meta.get("sheets", [])]


def guess_id_column_name(columns: list[str]) -> str | None:
    """
    Best-effort guess for an "ID" column, including common Hebrew variants.
    """
    cols = [str(c) for c in columns]
    lower = [c.strip().lower() for c in cols]

    # Exact matches first
    exact = {"id", "מזהה", "מספר מזהה"}
    for i, c in enumerate(lower):
        if c in exact:
            return cols[i]

    # Hebrew "ת״ז" variants (national ID) + generic ID-ish names
    keywords = [
        "ת\"ז",
        "ת״ז",
        "ת.ז",
        "תז",
        "תעודת זהות",
        "מספר זהות",
        "מספר תעודת זהות",
        "id",
        "מזהה",
    ]
    for i, orig in enumerate(cols):
        s = orig.strip()
        sl = s.lower()
        if any(k.lower() in sl for k in keywords):
            return orig

    return None


def _looks_int(s: str) -> bool:
    s2 = s.strip()
    if not s2:
        return False
    try:
        int(s2)
        return True
    except Exception:
        return False


def autofill_missing_ids_by_appearance(df: pd.DataFrame, id_col: str) -> pd.DataFrame:
    """
    Fills blank IDs top-to-bottom (order of appearance), without changing existing IDs.
    If existing IDs contain integers, new IDs continue from max+1; otherwise start at 1.
    """
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
    # Ensure serializable simple scalars
    for c in df2.columns:
        df2[c] = df2[c].map(lambda v: "" if v is None else str(v))
    return df2


def strip_bidi_marks_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Removes common bidi/direction markers that we may inject for better RTL/LTR display.
    """
    out = df.copy()
    marks = [
        "\u200e",  # LRM
        "\u200f",  # RLM
        "\u202a",  # LRE
        "\u202b",  # RLE
        "\u202c",  # PDF
        "\u202d",  # LRO
        "\u202e",  # RLO
        "\u2066",  # LRI
        "\u2067",  # RLI
        "\u2068",  # FSI
        "\u2069",  # PDI
    ]

    def _clean(v: object) -> str:
        s = "" if v is None else str(v)
        for m in marks:
            s = s.replace(m, "")
        return s

    for c in out.columns:
        out[c] = out[c].map(_clean)
    return out


def _is_blank_cell(v: object) -> bool:
    if v is None:
        return True
    s = str(v).strip()
    return s == "" or s.lower() == "nan"


def _parse_serial_number(v: object) -> int | None:
    """
    Parses numeric serial IDs.
    Also supports legacy 'Pa001' values by extracting the numeric part.
    """
    if v is None:
        return None
    s = str(v).strip()
    m = re.match(r"(?i)^pa0*(\d+)$", s)
    if m:
        s = m.group(1)
    if not s.isdigit():
        return None
    try:
        return int(s)
    except Exception:
        return None


def normalize_and_autofill_serial_numbers(df: pd.DataFrame, id_col: str) -> pd.DataFrame:
    """
    Ensures `id_col` contains only numbers (as text).
    - Converts legacy 'Pa001' → '1'
    - Fills blanks with max(existing)+1, max+2, ...
    """
    if id_col not in df.columns:
        return df

    out = df.copy()
    parsed = [_parse_serial_number(v) for v in out[id_col].tolist()]
    existing_nums = [n for n in parsed if n is not None]
    next_n = (max(existing_nums) + 1) if existing_nums else 1

    for idx in out.index.tolist():
        v = out.at[idx, id_col]
        if _is_blank_cell(v):
            out.at[idx, id_col] = str(next_n)
            next_n += 1
        else:
            # Convert legacy PaNNN to numeric text; keep other non-numeric as-is
            n = _parse_serial_number(v)
            if n is not None:
                out.at[idx, id_col] = str(n)

    return out


def _parse_birthdate_to_date(v: object) -> date | None:
    """
    Tries to parse a date from common Sheets/Excel representations.
    """
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() == "nan":
        return None

    # Try pandas parsing first (common: dd/mm/yyyy in IL)
    dt = pd.to_datetime(s, errors="coerce", dayfirst=True)
    if pd.notna(dt):
        try:
            return dt.date()
        except Exception:
            pass

    # Try Excel serial day number
    try:
        # Sheets sometimes returns integers for dates depending on formatting
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
    """
    Overwrites/creates age column based on birthdate column.
    """
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


def _count_allowed_days(text: object) -> int:
    if text is None:
        return 0
    # If the editor returns a list (MultiselectColumn), count from it.
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


def normalize_days_for_editor(df: pd.DataFrame, days_col: str) -> pd.DataFrame:
    """
    Converts 'ימי הגעה' cells from comma-separated string to list[str] for MultiselectColumn.
    """
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
        # stable unique
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
    """
    Converts list[str] from MultiselectColumn back to a comma-separated string for Sheets.
    """
    if days_col not in df.columns:
        return df

    out = df.copy()

    def _to_str(v: object) -> str:
        if v is None:
            return ""
        if isinstance(v, (list, tuple, set)):
            parts = [str(p).strip() for p in v]
            parts = [p for p in parts if p in DAYS_ALLOWED]
            # stable order as DAYS_OPTIONS
            ordered = [d for d in DAYS_OPTIONS if d in set(parts)]
            return ", ".join(ordered)
        s = str(v).strip()
        if not s or s.lower() == "nan":
            return ""
        return s

    out[days_col] = out[days_col].map(_to_str)
    return out


def normalize_exposure_for_editor(df: pd.DataFrame, exposure_col: str) -> pd.DataFrame:
    """
    Converts exposure column to bool for CheckboxColumn.
    Sheet stores: "יש" (True) / "אין" (False).
    Accepts some common variants too (V/X, True/False).
    Blank defaults to False ("אין").
    """
    if exposure_col not in df.columns:
        return df

    out = df.copy()
    truthy = {"יש", "v", "✓", "true", "1", "כן"}
    falsy = {"אין", "x", "✗", "false", "0", "לא"}

    def _to_bool(v: object) -> bool:
        if isinstance(v, bool):
            return v
        if v is None:
            return False
        s = str(v).strip()
        if not s or s.lower() == "nan":
            return False
        sl = s.lower()
        if sl in truthy:
            return True
        if sl in falsy:
            return False
        # If unknown text, default to False (safer for privacy)
        return False

    out[exposure_col] = out[exposure_col].map(_to_bool)
    return out


def normalize_exposure_for_save(df: pd.DataFrame, exposure_col: str) -> pd.DataFrame:
    """
    Converts exposure checkbox values to sheet values:
    True -> "יש", False -> "אין"
    """
    if exposure_col not in df.columns:
        return df

    out = df.copy()

    def _to_sheet(v: object) -> str:
        if isinstance(v, bool):
            return EXPOSURE_YES_VALUE if v else EXPOSURE_NO_VALUE
        if v is None:
            return EXPOSURE_NO_VALUE
        s = str(v).strip()
        if not s or s.lower() == "nan":
            return EXPOSURE_NO_VALUE
        # If someone typed/left strings, normalize common variants
        sl = s.lower()
        if sl in {"יש", "v", "✓", "true", "1", "כן"}:
            return EXPOSURE_YES_VALUE
        if sl in {"אין", "x", "✗", "false", "0", "לא"}:
            return EXPOSURE_NO_VALUE
        return EXPOSURE_NO_VALUE

    out[exposure_col] = out[exposure_col].map(_to_sheet)
    return out


def compute_required_payment(df: pd.DataFrame, days_col: str, payment_col: str) -> pd.DataFrame:
    """
    Sets payment_col = count(ימי הגעה)*80, counting unique allowed values in DAYS_ALLOWED.
    """
    if days_col not in df.columns:
        return df
    out = df.copy()
    payments = [str(_count_allowed_days(v) * PAYMENT_PER_DAY) for v in out[days_col].tolist()]
    if payment_col in out.columns:
        out[payment_col] = payments
    else:
        out.insert(len(out.columns), payment_col, payments)
    return out


def move_not_coming_to_bottom(df: pd.DataFrame, arrival_col: str) -> pd.DataFrame:
    """
    Stable sort: rows with arrival == 'לא מגיע' go to the end.
    """
    if arrival_col not in df.columns:
        return df
    out = df.copy()
    key = out[arrival_col].astype(str).map(lambda v: str(v).strip())
    out["_yated_sort_not_coming"] = (key == ARRIVAL_NOT_COMING_VALUE).astype(int)
    out = out.sort_values("_yated_sort_not_coming", kind="mergesort").drop(columns=["_yated_sort_not_coming"])
    return out


def apply_business_rules(df: pd.DataFrame) -> pd.DataFrame:
    """
    Applies all CRM rules before saving.
    """
    # Convert multiselect lists to strings before sanitizing (otherwise they become "['x']").
    out = normalize_days_for_save(df, days_col="ימי הגעה")
    out = normalize_exposure_for_save(out, exposure_col=EXPOSURE_COL_NAME)
    out = sanitize_df_for_sheet(out)
    out = strip_bidi_marks_df(out)
    out = normalize_and_autofill_serial_numbers(out, DEFAULT_ID_COLUMN_NAME)
    out = compute_age_column(out, birthdate_col="תאריך לידה", age_col="גיל")
    out = compute_required_payment(out, days_col="ימי הגעה", payment_col="תשלום נדרש")
    out = move_not_coming_to_bottom(out, arrival_col="הגעה")
    return out


def overwrite_sheet_from_a1(creds: Credentials, spreadsheet_id: str, worksheet_name: str, df: pd.DataFrame) -> None:
    """
    Overwrites values starting at A1 with: header row + all data rows.
    Clears a reasonably large area first to avoid stale leftover cells.
    """
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)

    df2 = apply_business_rules(df)
    values = [list(df2.columns)] + df2.values.tolist()

    # Clear a big block to remove old leftovers (values only; formatting stays).
    clear_end_col = _col_num_to_a1(max(26, len(df2.columns) + 10))  # at least A:Z
    clear_range = f"'{worksheet_name}'!A1:{clear_end_col}5000"
    sheets.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id, range=clear_range, body={}
    ).execute()

    # Write new values from A1
    sheets.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'{worksheet_name}'!A1",
        valueInputOption="USER_ENTERED",
        body={"values": values},
    ).execute()


st.set_page_config(page_title="Google Sheet editor", layout="wide")
st.title("CRM table (Google Sheets)")
st.caption("View, edit, and add people rows in your main CRM spreadsheet.")

with st.sidebar:
    st.subheader("Spreadsheet")
    # Hide the spreadsheet ID from the UI; keep it configurable via secrets if needed.
    spreadsheet_id = st.secrets.get("spreadsheet_id", DEFAULT_SPREADSHEET_ID)
    refresh = st.button("Refresh data")

try:
    creds = get_credentials()
    meta = get_spreadsheet_metadata(creds, spreadsheet_id)
    titles = list_worksheet_titles(meta)
    if not titles:
        raise RuntimeError("Spreadsheet has no worksheets (tabs).")
except Exception as e:
    st.error(str(e))
    st.stop()

if refresh:
    st.cache_data.clear()

with st.sidebar:
    worksheet_title = st.selectbox("Worksheet (tab)", options=titles, index=0)

df = read_sheet_as_df(creds, spreadsheet_id, worksheet_name=worksheet_title)

st.subheader("Saved data (edit directly in the table)")
if df.empty:
    st.info("Sheet looks empty. Add headers in row 1 in Google Sheets, then refresh.")
    st.stop()

st.caption("Add new people by using the table’s built-in “add row”. Missing IDs will be auto-filled on save.")

filter_text = st.text_input("חיפוש מהיר (בכל העמודות)", value="")
base_df = df
base_cols = list(base_df.columns)
view_cols = base_cols  # show columns exactly as they appear in the sheet

display_df = base_df[view_cols]
if filter_text.strip():
    needle = filter_text.strip().lower()
    mask = base_df.astype(str).apply(lambda row: row.str.lower().str.contains(needle, na=False)).any(axis=1)
    display_df = base_df.loc[mask, view_cols]

morning_col_name = "מסגרת בוקר"
arrival_col_name = "הגעה"
days_col_name = "ימי הגעה"
payment_col_name = "תשלום נדרש"
age_col_name = "גיל"
morning_age_highlight_col = "מסגרת בוקר (גיל>20)"
exposure_col_name = EXPOSURE_COL_NAME
exposure_status_col = "אישור חשיפה (V/X)"

# Prepare editor-friendly values
display_df = normalize_days_for_editor(display_df, days_col=days_col_name)
display_df = normalize_exposure_for_editor(display_df, exposure_col=exposure_col_name)
display_df = compute_age_column(display_df, birthdate_col="תאריך לידה", age_col=age_col_name)
display_df = compute_required_payment(display_df, days_col=days_col_name, payment_col=payment_col_name)

if age_col_name in display_df.columns and morning_col_name in display_df.columns:
    # Helper column we can color red reliably (Streamlit cannot conditionally color editable cells).
    def _morning_if_over_20(v: object) -> str:
        try:
            n = int(str(v).strip())
            if n > 20:
                return str(display_df.loc[v.name, morning_col_name]).strip()
            return ""
        except Exception:
            return ""

    # Use a Series with access to row index
    display_df[morning_age_highlight_col] = display_df[age_col_name].copy()
    display_df[morning_age_highlight_col] = display_df[morning_age_highlight_col].rename("age").to_frame().apply(
        lambda r: _morning_if_over_20(r["age"]),
        axis=1,
    )

if exposure_col_name in display_df.columns:
    display_df[exposure_status_col] = display_df[exposure_col_name].map(lambda b: "V" if bool(b) else "X")

disabled_cols = [
    c
    for c in [
        DEFAULT_ID_COLUMN_NAME,
        age_col_name,
        payment_col_name,
        morning_age_highlight_col,
        exposure_status_col,
    ]
    if c in display_df.columns
]

def _style_red_if_nonempty(v: object) -> str:
    s = "" if v is None else str(v).strip()
    return "background-color: #ffb3b3;" if s else ""


def _style_red_if_x(v: object) -> str:
    s = "" if v is None else str(v).strip().upper()
    return "background-color: #ffb3b3;" if s == "X" else ""

styled_editor_df = display_df
if morning_age_highlight_col in display_df.columns or exposure_status_col in display_df.columns:
    styler = display_df.style
    if morning_age_highlight_col in display_df.columns:
        styler = styler.applymap(_style_red_if_nonempty, subset=[morning_age_highlight_col])
    if exposure_status_col in display_df.columns:
        styler = styler.applymap(_style_red_if_x, subset=[exposure_status_col])
    styled_editor_df = styler

edited_df = st.data_editor(
    styled_editor_df,
    use_container_width=True,
    hide_index=True,
    num_rows="dynamic",
    disabled=disabled_cols,
    column_config={
        **(
            {
                morning_col_name: st.column_config.TextColumn(
                    label=morning_col_name,
                    help=f"אפשר להקליד טקסט חופשי. ערכים נפוצים: {', '.join(MORNING_FRAMEWORK_OPTIONS)}",
                )
            }
            if morning_col_name in display_df.columns
            else {}
        ),
        **(
            {
                morning_age_highlight_col: st.column_config.TextColumn(
                    label=morning_age_highlight_col,
                    width="medium",
                    help="מראה את ערך 'מסגרת בוקר' באדום כאשר גיל מעל 20 (לתצוגה בלבד).",
                )
            }
            if morning_age_highlight_col in display_df.columns
            else {}
        ),
        **(
            {
                exposure_col_name: st.column_config.CheckboxColumn(
                    label=exposure_col_name,
                    help="V = יש, X = אין. אם לא מסומן — יישמר 'אין'.",
                    default=False,
                )
            }
            if exposure_col_name in display_df.columns
            else {}
        ),
        **(
            {
                exposure_status_col: st.column_config.TextColumn(
                    label=exposure_status_col,
                    width="small",
                    help="לתצוגה בלבד. צבוע באדום כאשר X (אין).",
                )
            }
            if exposure_status_col in display_df.columns
            else {}
        ),
        **(
            {
                arrival_col_name: st.column_config.SelectboxColumn(
                    label=arrival_col_name,
                    options=ARRIVAL_OPTIONS,
                    required=False,
                )
            }
            if arrival_col_name in display_df.columns
            else {}
        ),
        **(
            {
                days_col_name: st.column_config.MultiselectColumn(
                    label=days_col_name,
                    options=DAYS_OPTIONS,
                    accept_new_options=False,
                    default=[],
                    help='בחר/י יום אחד או יותר. התשלום יחושב אוטומטית לפי מספר הימים שנבחרו.',
                )
            }
            if days_col_name in display_df.columns
            else {}
        ),
    },
)
c1, c2, c3, c4 = st.columns([1, 1, 2, 2])
with c1:
    st.metric("שורות", len(df))
with c2:
    st.metric("עמודות", len(df.columns))
with c3:
    csv = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button("הורדת CSV", data=csv, file_name="crm_export.csv", mime="text/csv")
with c4:
    if st.button("שמירת שינויים ל‑Google Sheets", type="primary"):
        try:
            if filter_text.strip():
                st.error("כדי לשמור שינויים, קודם לנקות את החיפוש (כדי לא לשמור רק תת‑קבוצה).")
            else:
                # Never write UI-only helper columns to the sheet.
                edited_to_save = edited_df
                try:
                    edited_to_save = edited_to_save.reindex(columns=base_cols, fill_value="")
                except Exception:
                    # If the editor returned a non-DataFrame, fall back to saving as-is.
                    pass
                overwrite_sheet_from_a1(creds, spreadsheet_id, worksheet_title, edited_to_save)
                st.success("נשמר. מרענן…")
                st.cache_data.clear()
                st.rerun()
        except Exception as e:
            st.error(f"נכשל לשמור שינויים: {e}")
