"""Lifetime panel (spec/lifetime-panel.yaml): the Census summing rule and the cell rules, on small fixtures."""
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_acs5_panels as b  # noqa: E402


class Lifetime(unittest.TestCase):
    def test_julian_kominski_worked_example(self):
        """J&K (2011) p. 5: eight full-time, year-round band medians, each x 5, sum to $1,743,235."""
        meds = [33202, 39740, 44098, 45287, 46677, 47411, 47310, 44922]
        self.assertEqual(b.worklife(meds), 1743235)

    def fixture(self, per_band, value=1000.0):
        age = np.repeat([lo for lo, _ in b.BANDS], per_band)
        pay = np.full(len(age), value) + np.arange(len(age)) % 7
        W = np.ones((len(age), 81)) * 10
        W[:, 1::2] += 1                                         # replicates differ a little
        return pay, W, age

    def test_cell_total_is_five_times_band_medians(self):
        c, T = b.lifetime_cell(*self.fixture(120))
        self.assertFalse(c["hidden"], c["reason"])
        self.assertEqual(len(c["bands"]), 8)
        self.assertAlmostEqual(c["total"], 5 * sum(x["median"] for x in c["bands"]), places=2)
        self.assertEqual(T.shape, (81,))

    def test_small_band_hides(self):
        pay, W, age = self.fixture(120)
        keep = ~((age == 60) & (np.arange(len(age)) % 120 >= 50))   # band 60-64 keeps 50 people
        c, _ = b.lifetime_cell(pay[keep], W[keep], age[keep])
        self.assertTrue(c["hidden"])
        self.assertIn("60-64", c["reason"])

    def test_empty_band_hides(self):
        pay, W, age = self.fixture(120)
        keep = age != 25
        c, T = b.lifetime_cell(pay[keep], W[keep], age[keep])
        self.assertTrue(c["hidden"])
        self.assertIsNone(T)


if __name__ == "__main__":
    unittest.main()
