from __future__ import annotations

import json
from typing import Any

import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

DEFAULT_SPREADSHEET_ID = "19261I9RJbS0Cnar6Ex0nnWa_gZqb3lGdM7L-gfv_gWs"

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
      private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
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
        "Streamlit Cloud -> App -> Settings -> Secrets."
    )


def build_sheets_service(creds: Credentials):
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def _normalize_headers(headers: list[str], width: int) -> list[str]:
    headers = [h.strip() if isinstance(h, str) else "" for h in headers]
    headers = headers[:width] + [""] * max(0, width - len(headers))
    out = []
    seen: dict[str, int] = {}
    for i, h in enumerate(headers):
        base = h if h else f"col_{i+1}"
        n = seen.get(base, 0)
        seen[base] = n + 1
        out.append(base if n == 0 else f"{base}_{n+1}")
    return out


def _a1_range_for_all(sheet_name: str) -> str:
    return f"'{sheet_name}'"


def read_sheet_as_df(service, spreadsheet_id: str, worksheet_name: str) -> pd.DataFrame:
    values_resp = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=_a1_range_for_all(worksheet_name))
        .execute()
    )
    values = values_resp.get("values", [])
    if not values:
        return pd.DataFrame()

    width = max(len(r) for r in values)
    headers = _normalize_headers(values[0], width)
    rows = [r + [""] * (width - len(r)) for r in values[1:]]
    return pd.DataFrame(rows, columns=headers)


def _col_num_to_a1(col_num_1_based: int) -> str:
    if col_num_1_based <= 0:
        raise ValueError("col_num_1_based must be >= 1")
    s = ""
    n = col_num_1_based
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def write_df_to_sheet(service, spreadsheet_id: str, worksheet_name: str, df: pd.DataFrame) -> None:
    if df.empty:
        values = [[]]
    else:
        values = [list(df.columns)] + df.values.tolist()

    clear_end_col = _col_num_to_a1(max(26, len(df.columns) + 10))
    clear_range = f"'{worksheet_name}'!A1:{clear_end_col}5000"
    service.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id, range=clear_range, body={}
    ).execute()

    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'{worksheet_name}'!A1",
        valueInputOption="USER_ENTERED",
        body={"values": values},
    ).execute()


def append_row(service, spreadsheet_id: str, worksheet_name: str, row_values: list[str]) -> None:
    end_col = _col_num_to_a1(max(1, len(row_values)))
    read_range = f"'{worksheet_name}'!A1:{end_col}"
    existing = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=read_range)
        .execute()
    )
    existing_values = existing.get("values", [])
    next_row = len(existing_values) + 1

    write_range = f"'{worksheet_name}'!A{next_row}:{end_col}{next_row}"
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=write_range,
        valueInputOption="USER_ENTERED",
        body={"values": [row_values]},
    ).execute()


def list_worksheet_titles(service, spreadsheet_id: str) -> list[str]:
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    return [s["properties"]["title"] for s in meta.get("sheets", [])]


def ensure_sheet_exists(service, spreadsheet_id: str, worksheet_name: str) -> None:
    titles = list_worksheet_titles(service, spreadsheet_id)
    if worksheet_name in titles:
        return
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{"addSheet": {"properties": {"title": worksheet_name}}}]},
    ).execute()


def ensure_sheets(service, spreadsheet_id: str, worksheet_names: list[str]) -> None:
    titles = set(list_worksheet_titles(service, spreadsheet_id))
    requests = []
    for name in worksheet_names:
        if name not in titles:
            requests.append({"addSheet": {"properties": {"title": name}}})
    if requests:
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": requests}
        ).execute()
