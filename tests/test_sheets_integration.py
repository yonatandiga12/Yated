import unittest
from unittest import mock

import pandas as pd

import yated.sheets as sheets


class SheetsIntegrationTests(unittest.TestCase):
    def test_read_sheet_as_df(self):
        service = mock.Mock()
        service.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {
            "values": [["A", "B"], ["1", "2"]]
        }
        df = sheets.read_sheet_as_df(service, "spreadsheet", "Sheet1")
        self.assertEqual(list(df.columns), ["A", "B"])
        self.assertEqual(df.loc[0, "A"], "1")

    def test_ensure_sheet_exists_adds_missing(self):
        service = mock.Mock()
        with mock.patch("yated.sheets.list_worksheet_titles") as mock_titles:
            mock_titles.return_value = ["Existing"]
            sheets.ensure_sheet_exists(service, "spreadsheet", "NewSheet")
            service.spreadsheets.return_value.batchUpdate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
