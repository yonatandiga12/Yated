import json

import pandas as pd
import streamlit as st

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build


DRIVE_FOLDER_ID = "1XZ9fZUusUYO1IpJFUZ8tlQ0NdIu0tPAq"
TARGET_SHEET_NAME = "hi"


SCOPES = [
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
def find_spreadsheet_file_id(_creds: Credentials, folder_id: str, sheet_name: str) -> str:
    # Note: Streamlit cache can't hash google Credentials objects, so we prefix with _
    drive = build("drive", "v3", credentials=_creds, cache_discovery=False)
    q = (
        f"'{folder_id}' in parents and "
        "mimeType='application/vnd.google-apps.spreadsheet' and "
        f"name='{sheet_name}' and trashed=false"
    )
    res = (
        drive.files()
        .list(q=q, fields="files(id,name)", pageSize=10, supportsAllDrives=True)
        .execute()
    )
    files = res.get("files", [])
    if not files:
        raise RuntimeError(
            f"Couldn't find a Google Sheet named '{sheet_name}' in that folder. "
            "Make sure the folder is shared with the service account email."
        )
    return files[0]["id"]


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


def read_sheet_as_df(creds: Credentials, spreadsheet_id: str, worksheet_name: str = None) -> pd.DataFrame:
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)

    meta = sheets.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    sheet_titles = [s["properties"]["title"] for s in meta.get("sheets", [])]
    if not sheet_titles:
        return pd.DataFrame()

    title = worksheet_name or sheet_titles[0]
    values_resp = (
        sheets.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=_a1_range_for_all(title))
        .execute()
    )
    values = values_resp.get("values", [])
    if not values:
        return pd.DataFrame()

    width = max(len(r) for r in values)
    headers = _normalize_headers(values[0], width)
    rows = [r + [""] * (width - len(r)) for r in values[1:]]
    return pd.DataFrame(rows, columns=headers)


def append_row(creds: Credentials, spreadsheet_id: str, worksheet_name: str, row_values: list[str]) -> None:
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    body = {"values": [row_values]}
    sheets.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=_a1_range_for_all(worksheet_name),
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body=body,
    ).execute()


def get_first_worksheet_title(creds: Credentials, spreadsheet_id: str) -> str:
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    meta = sheets.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    sheet_titles = [s["properties"]["title"] for s in meta.get("sheets", [])]
    return sheet_titles[0] if sheet_titles else "Sheet1"


st.set_page_config(page_title="Google Sheet editor", layout="wide")
st.title("Google Sheet viewer + row adder")
st.caption("Reads the Google Sheet named 'hi' from your Drive folder, and appends rows.")

with st.sidebar:
    st.subheader("Source")
    st.text(f"Drive folder: {DRIVE_FOLDER_ID}")
    st.text(f"Sheet name: {TARGET_SHEET_NAME}")
    refresh = st.button("Refresh table")

try:
    creds = get_credentials()
    spreadsheet_id = find_spreadsheet_file_id(creds, DRIVE_FOLDER_ID, TARGET_SHEET_NAME)
    worksheet_title = get_first_worksheet_title(creds, spreadsheet_id)
except Exception as e:
    st.error(str(e))
    st.stop()

if refresh:
    st.cache_data.clear()

df = read_sheet_as_df(creds, spreadsheet_id, worksheet_name=worksheet_title)

left, right = st.columns([2, 1], gap="large")

with left:
    st.subheader("Current data")
    if df.empty:
        st.info("Sheet is empty (or only has headers). Add the first row using the form on the right.")
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)

with right:
    st.subheader("Add a row")
    if df.empty:
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
        submitted = st.form_submit_button("Append row")

    if submitted:
        row = [inputs[c] for c in cols]
        try:
            append_row(creds, spreadsheet_id, worksheet_title, row)
            st.success("Row appended. Click Refresh table to see it.")
        except Exception as e:
            st.error(f"Failed to append row: {e}")
