import json

import pandas as pd
import streamlit as st

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build


DEFAULT_SPREADSHEET_ID = "19261I9RJbS0Cnar6Ex0nnWa_gZqb3lGdM7L-gfv_gWs"


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


def overwrite_sheet_from_a1(creds: Credentials, spreadsheet_id: str, worksheet_name: str, df: pd.DataFrame) -> None:
    """
    Overwrites values starting at A1 with: header row + all data rows.
    Clears a reasonably large area first to avoid stale leftover cells.
    """
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)

    df2 = sanitize_df_for_sheet(df)

    # Auto-fill missing IDs (if we can find an ID column)
    forced_id_col = st.secrets.get("id_column_name") if hasattr(st, "secrets") else None
    id_col = forced_id_col or guess_id_column_name(list(df2.columns))
    if id_col:
        df2 = autofill_missing_ids_by_appearance(df2, id_col)
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

st.markdown(
    """
<style>
/* Make the app feel RTL for Hebrew */
html, body, [data-testid="stAppViewContainer"] {
  direction: rtl;
}
[data-testid="stAppViewContainer"] * {
  direction: rtl;
  text-align: right;
}
/* Keep code blocks readable */
code, pre, textarea {
  direction: ltr !important;
  text-align: left !important;
}
/* Sidebar RTL */
[data-testid="stSidebar"] {
  direction: rtl;
}
</style>
""",
    unsafe_allow_html=True,
)

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
display_df = df
if filter_text.strip():
    needle = filter_text.strip().lower()
    mask = df.astype(str).apply(lambda row: row.str.lower().str.contains(needle, na=False)).any(axis=1)
    display_df = df[mask]

edited_df = st.data_editor(
    display_df,
    use_container_width=True,
    hide_index=True,
    num_rows="dynamic",
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
                overwrite_sheet_from_a1(creds, spreadsheet_id, worksheet_title, edited_df)
                st.success("נשמר. מרענן…")
                st.cache_data.clear()
                st.rerun()
        except Exception as e:
            st.error(f"נכשל לשמור שינויים: {e}")
