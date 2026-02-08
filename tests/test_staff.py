import unittest
from datetime import date

import pandas as pd

from yated.staff import (
    compute_hourly_totals,
    apply_hourly_totals,
    compute_remaining_hours,
    build_staff_backup_df,
    summarize_staff_by_scholarship,
    should_rollover,
)


class StaffRulesTests(unittest.TestCase):
    def test_hour_totals_and_remaining(self):
        attendance = pd.DataFrame({"Serial Number": ["1", "1", "2"], "Hours": ["2", "3", "4"]})
        totals = compute_hourly_totals(attendance, "Serial Number", "Hours")
        staff = pd.DataFrame({"Serial Number": ["1", "2"], "Annual Hours": ["10", "8"]})
        staff = apply_hourly_totals(staff, "Serial Number", "Hourly Total", totals)
        staff = compute_remaining_hours(staff, "Annual Hours", "Hourly Total", "Remaining Hours")
        self.assertEqual(staff.loc[0, "Hourly Total"], "5.0")
        self.assertEqual(staff.loc[0, "Remaining Hours"], "5.0")

    def test_backup_and_summary(self):
        staff = pd.DataFrame({"Serial Number": ["1"], "Scholarship": ["Perach"], "Weekly Hours": ["4"]})
        backup = build_staff_backup_df(staff, year=2026, hours_debt_col="Hours Debt",
                                       remove_cols=["Weekly Hours"], year_col="Year")
        self.assertIn("Hours Debt", backup.columns)
        self.assertIn("Year", backup.columns)
        summary = summarize_staff_by_scholarship(backup, "Scholarship", "Year")
        self.assertFalse(summary.empty)

    def test_should_rollover(self):
        self.assertTrue(should_rollover(2025, today=date(2026, 9, 1)))
        self.assertFalse(should_rollover(2026, today=date(2026, 8, 31)))


if __name__ == "__main__":
    unittest.main()
