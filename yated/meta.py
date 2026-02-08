import pandas as pd

from .sheets import read_sheet_as_df, write_df_to_sheet

META_SHEET = "__meta"


def get_meta(service, spreadsheet_id: str) -> dict[str, str]:
    df = read_sheet_as_df(service, spreadsheet_id, META_SHEET)
    if df.empty or "Key" not in df.columns or "Value" not in df.columns:
        return {}
    return {str(k): str(v) for k, v in zip(df["Key"].tolist(), df["Value"].tolist())}


def set_meta(service, spreadsheet_id: str, updates: dict[str, str]) -> None:
    data = get_meta(service, spreadsheet_id)
    data.update({str(k): str(v) for k, v in updates.items()})
    df = pd.DataFrame({"Key": list(data.keys()), "Value": list(data.values())})
    write_df_to_sheet(service, spreadsheet_id, META_SHEET, df)
