import unittest
from datetime import date

import pandas as pd

from yated.attendance import (
    build_participant_daily_attendance,
    build_staff_daily_attendance,
    summarize_participant_attendance,
    summarize_participant_attendance_yearly,
)


class AttendanceTests(unittest.TestCase):
    def test_build_participant_attendance(self):
        participants = pd.DataFrame({
            "Serial Number": ["1"],
            "First Name": ["Nina"],
            "Attendance Days": ["Monday"],
            "Attendance": ["✓"],
        })
        df = build_participant_daily_attendance(
            participants,
            attendance_days_col="Attendance Days",
            attendance_flag_col="Attendance",
            serial_col="Serial Number",
            name_col="First Name",
            day_name="Monday",
            attendance_date=date(2026, 2, 8),
        )
        self.assertEqual(df.loc[0, "Expected"], "Yes")

    def test_build_staff_attendance(self):
        staff = pd.DataFrame({
            "Serial Number": ["1"],
            "First Name": ["Liam"],
            "Last Name": ["Smith"],
            "Scholarship": ["Perach"],
            "Current Day": ["Monday"],
        })
        df = build_staff_daily_attendance(
            staff,
            current_day_col="Current Day",
            serial_col="Serial Number",
            first_name_col="First Name",
            last_name_col="Last Name",
            scholarship_col="Scholarship",
            day_name="Monday",
            attendance_date=date(2026, 2, 8),
        )
        self.assertEqual(df.loc[0, "Expected"], "Yes")

    def test_participant_summary(self):
        attendance = pd.DataFrame({
            "Date": ["2026-02-08", "2026-02-15"],
            "Serial Number": ["1", "1"],
            "Participant Name": ["Nina", "Nina"],
            "Attended": ["Yes", "No"],
        })
        summary = summarize_participant_attendance(attendance, "Serial Number", "Participant Name", "Attended")
        self.assertEqual(summary.loc[0, "Attendances"], 1)

    def test_participant_yearly_summary(self):
        participants = pd.DataFrame({
            "Serial Number": ["1", "2"],
            "First Name": ["Nina", "Adam"],
            "Last Name": ["A", "B"],
            "Attendance": ["✓", "X"],
        })
        attendance = pd.DataFrame({
            "Date": ["2026-02-08", "2026-02-15", "2026-02-15"],
            "Serial Number": ["1", "1", "2"],
            "Attended": ["Yes", "No", "Yes"],
        })
        summary = summarize_participant_attendance_yearly(
            attendance_df=attendance,
            participants_df=participants,
            year=2026,
            participants_serial_col="Serial Number",
            participants_name_col="First Name",
            participants_last_name_col="Last Name",
            participants_attendance_col="Attendance",
            attendance_serial_col="Serial Number",
            attended_col="Attended",
        )
        self.assertEqual(len(summary), 1)
        self.assertEqual(summary.loc[0, "Participant Name"], "Nina A")


if __name__ == "__main__":
    unittest.main()
