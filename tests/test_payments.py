import unittest

import pandas as pd

from yated.payments import build_billing_table


class PaymentsTests(unittest.TestCase):
    def test_billing_table_partial(self):
        participants = pd.DataFrame({
            "Serial Number": ["1"],
            "First Name": ["Nina"],
            "Required Payment": ["160"],
        })
        payments = pd.DataFrame({
            "Participant Serial": ["1"],
            "Amount": ["80"],
            "Payment Date": ["2026-11-01"],
            "Month": ["November"],
        })
        billing = build_billing_table(
            participants_df=participants,
            payments_df=payments,
            serial_col="Serial Number",
            name_col="First Name",
            required_col="Required Payment",
            payment_serial_col="Participant Serial",
            payment_amount_col="Amount",
            payment_date_col="Payment Date",
            payment_month_col="Month",
        )
        self.assertTrue(billing.partial_mask)
        self.assertEqual(billing.df.loc[0, "November"], "80.0")


if __name__ == "__main__":
    unittest.main()
