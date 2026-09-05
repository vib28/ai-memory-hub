import unittest

from memory_hub.security import check_text

class SecurityCardRegexTests(unittest.TestCase):
    def test_sap_number_range_is_not_flagged(self):
        result = check_text("SAP number range interval Z2 runs 2000000000001 to 2000000009999.")
        self.assertTrue(result.safe, result.reason)

    def test_small_integer_list_is_not_flagged(self):
        result = check_text("Ticket IDs to review: 1, 2, 3, 4, 5, 6, 7, 8, 9, 10.")
        self.assertTrue(result.safe, result.reason)

    def test_real_looking_visa_number_is_flagged(self):
        # 4111 1111 1111 1111 is the standard Luhn-valid Visa test number.
        result = check_text("Card on file: 4111 1111 1111 1111")
        self.assertFalse(result.safe)
        self.assertIn("payment", result.reason)

    def test_api_key_still_flagged(self):
        result = check_text("api_key: sk-abcdefghijklmnopqrstuvwxyz123456")
        self.assertFalse(result.safe)

if __name__ == "__main__":
    unittest.main()
