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
    spreadsheet_id = st.text_input("Spreadsheet ID", value=DEFAULT_SPREADSHEET_ID)
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

top_left, top_right = st.columns([3, 2], gap="large")

with top_left:
    st.subheader("Saved data")
    if df.empty:
        st.info("Sheet looks empty. Add headers in row 1 in Google Sheets, then refresh.")
        st.stop()

    filter_text = st.text_input("Quick filter (search across all columns)", value="")
    display_df = df
    if filter_text.strip():
        needle = filter_text.strip().lower()
        mask = df.astype(str).apply(lambda row: row.str.lower().str.contains(needle, na=False)).any(axis=1)
        display_df = df[mask]

    st.caption("Tip: you can edit cells directly in the grid below, add rows, then click Save edits.")
    edited_df = st.data_editor(
        display_df,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
    )

    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        st.metric("Rows", len(df))
    with c2:
        st.metric("Columns", len(df.columns))
    with c3:
        csv = df.to_csv(index=False).encode("utf-8-sig")
        st.download_button("Download CSV", data=csv, file_name="crm_export.csv", mime="text/csv")

    if st.button("Save edits to Google Sheets", type="primary"):
        try:
            # If user filtered, we must avoid accidentally saving only filtered subset.
            # So: if a filter is active, block saving (to avoid data loss).
            if filter_text.strip():
                st.error("Clear the filter before saving edits (to avoid overwriting with a subset).")
            else:
                overwrite_sheet_from_a1(creds, spreadsheet_id, worksheet_title, edited_df)
                st.success("Saved. Refreshing…")
                st.cache_data.clear()
                st.rerun()
        except Exception as e:
            st.error(f"Failed to save edits: {e}")

with top_right:
    st.subheader("Add a row")
    if df.shape[1] == 0:
        st.warning(
            "I couldn't infer columns (sheet may be empty). "
            "Add headers as the first row directly in Google Sheets, then refresh."
        )
        st.stop()

    cols = list(df.columns)
    with st.form("add_row_form", clear_on_submit=True):
        inputs = {}
        for c in cols:
            inputs[c] = st.text_input(c)
        submitted = st.form_submit_button("Append row (adds a new person)")

    if submitted:
        row = [inputs[c] for c in cols]
        try:
            append_row(creds, spreadsheet_id, worksheet_title, row)
            st.success("Row appended. Refreshing…")
            st.cache_data.clear()
            st.rerun()
        except Exception as e:
            st.error(f"Failed to append row: {e}")
