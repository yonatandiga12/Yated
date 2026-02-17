import unittest
from datetime import date

import pandas as pd

from yated.participants import (
    compute_age_column,
    normalize_days_for_editor,
    normalize_days_for_save,
    compute_required_payment,
    normalize_media_consent_for_editor,
    normalize_media_consent_for_save,
    normalize_attendance_for_editor,
    normalize_attendance_for_save,
    move_absent_to_bottom,
    build_morning_framework_alert_mask,
)


class ParticipantRulesTests(unittest.TestCase):
    def test_compute_age_column(self):
        df = pd.DataFrame({"Date of Birth": ["2000-02-08", ""]})
        out = compute_age_column(df, "Date of Birth", "Age")
        self.assertIn("Age", out.columns)
        self.assertEqual(out.loc[1, "Age"], "")

    def test_days_normalization_roundtrip(self):
        df = pd.DataFrame({"Attendance Days": ["Monday, Tuesday", "Wednesday"]})
        editor = normalize_days_for_editor(df, "Attendance Days")
        self.assertEqual(editor.loc[0, "Attendance Days"], ["Monday", "Tuesday"])
        saved = normalize_days_for_save(editor, "Attendance Days")
        self.assertEqual(saved.loc[0, "Attendance Days"], "Monday, Tuesday")

    def test_required_payment(self):
        df = pd.DataFrame({"Attendance Days": ["Monday, Tuesday", ""]})
        out = compute_required_payment(df, "Attendance Days", "Required Payment")
        self.assertEqual(out.loc[0, "Required Payment"], "160")
        self.assertEqual(out.loc[1, "Required Payment"], "0")

    def test_media_consent_year(self):
        df = pd.DataFrame({"Media Consent": ["✓", ""], "Media Consent Year": ["2026", ""]})
        state = normalize_media_consent_for_editor(df, "Media Consent", "Media Consent Year", 2026)
        self.assertTrue(state.df.loc[0, "Media Consent"])
        self.assertFalse(state.df.loc[1, "Media Consent"])
        saved = normalize_media_consent_for_save(state.df, "Media Consent", "Media Consent Year", 2026)
        self.assertEqual(saved.loc[0, "Media Consent"], "✓")

    def test_attendance_sort(self):
        df = pd.DataFrame({
            "Attendance": ["✓", "X", "✓"],
            "First Name": ["A", "B", "C"],
        })
        out = move_absent_to_bottom(df, "Attendance", ["First Name"])
        self.assertEqual(out.iloc[-1]["Attendance"], "X")

    def test_morning_framework_alert_mask(self):
        today = date(2026, 2, 8)
        df = pd.DataFrame({
            "Date of Birth": ["2005-03-08", "2004-01-01"],
            "Morning Framework": ["Shahar", "Maash"],
        })
        mask = build_morning_framework_alert_mask(df, "Date of Birth", "Morning Framework", today=today)
        self.assertEqual(mask, [True, False])

    def test_morning_framework_alert_mask_case_insensitive_and_trimmed(self):
        today = date(2026, 2, 8)
        df = pd.DataFrame({
            "Date of Birth": ["2005-03-08", "2005-03-08", "2005-03-08"],
            "Morning Framework": ["shahar", "  DEKALIM  ", "Yesodot"],
        })
        mask = build_morning_framework_alert_mask(df, "Date of Birth", "Morning Framework", today=today)
        self.assertEqual(mask, [True, True, True])

    def test_morning_framework_alert_mask_hebrew_aliases(self):
        today = date(2026, 2, 8)
        df = pd.DataFrame({
            "Date of Birth": ["2005-03-08", "2005-03-08", "2005-03-08", "2005-03-08"],
            "Morning Framework": ["שחר", "דקלים", "יסודות", "אילנות"],
        })
        mask = build_morning_framework_alert_mask(df, "Date of Birth", "Morning Framework", today=today)
        self.assertEqual(mask, [True, True, True, True])


if __name__ == "__main__":
    unittest.main()
