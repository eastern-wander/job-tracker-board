import unittest
from pathlib import Path
import core, discovery, product_policy

class PublicDefaultsTests(unittest.TestCase):
    def test_neutral_defaults_and_empty_sources(self):
        self.assertEqual(core.DEFAULT["timezone"], "UTC")
        self.assertEqual(core.DEFAULT["schedule"], "09:00")
        self.assertEqual(core.DEFAULT["priority_locations"], [])
        self.assertEqual(core.DEFAULT["boards"], "")
        self.assertEqual(core.DEFAULT["lever_boards"], "")
        self.assertEqual(discovery.LEVER_EMPLOYERS, {})
        self.assertEqual(discovery.ASHBY_EMPLOYERS, {})
        self.assertEqual(discovery.location_priority("Vancouver"), 0)
        self.assertEqual(discovery.location_priority("Dubai"), 0)

    def test_manual_time_ui_uses_utc(self):
        text=Path(__file__).with_name("ui.js").read_text()
        self.assertIn('function utcOffset(local){ return "+00:00"; }', text)
        self.assertNotIn("vancouverOffset", text)

    def test_no_implicit_employer_industry_override(self):
        self.assertEqual(discovery.SECTORS, {})
