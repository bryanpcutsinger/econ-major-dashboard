"""Step 11.1 checks (spec/scheduler.yaml): the vintage config derives the live paths and labels; fetch_inputs keeps
a matching file, deletes a download whose sha256 differs (exit 2), and stops on an input with no record (exit 3).
No network: downloads are replaced by a stub.

Run from the repo root:  python3 -m unittest discover -s tests -v
"""
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import fetch_inputs  # noqa: E402
import vintage  # noqa: E402


class Vintage(unittest.TestCase):
    def test_live_labels(self):
        v = vintage.V
        live = json.loads((ROOT / "data" / "current.json").read_text())["bundle"]
        self.assertTrue(live.startswith(v.bundle_prefix))
        self.assertEqual(v.years, {"rank": "ACS 2024 1-year", "other": "ACS 2020-24 5-year"})
        self.assertEqual((v.acs1_id, v.acs5_id), ("acs1-2024", "acs5-2020-2024"))

    def test_other_vintage(self):
        tmp = Path(tempfile.mkdtemp())
        f = tmp / "v.json"
        f.write_text(json.dumps({"acs1": 2025, "acs5": [2021, 2025], "onet_release": "30_2",
                                 "onet_link": "8digit_mean", "puma_vintage": 2020}))
        v = vintage.Vintage(f)
        self.assertEqual(v.bundle_prefix, "2025-1yr_2021-25-5yr_")
        self.assertTrue(str(v.acs5_zip).endswith("raw/acs5-2021-2025/csv_pus.zip"))
        self.assertIn("/pums/2025/5-Year/csv_pus.zip", v.urls[v.acs5_zip])
        self.assertNotIn("2024", " ".join(str(p) for p in v.urls) + " ".join(v.urls.values()))
        shutil.rmtree(tmp)


class Fetch(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.body = b"hello"
        self.key = str(vintage.V.socp_codes.relative_to(ROOT))
        self.rec = self.tmp / "inputs.json"
        self.saved = (fetch_inputs.RECORD, fetch_inputs.download, fetch_inputs.wanted)
        fetch_inputs.RECORD = self.rec
        fetch_inputs.wanted = lambda pums: [vintage.V.socp_codes]
        def stub(url, dest):
            dest.parent.mkdir(parents=True, exist_ok=True)
            t = dest.parent / ".part-test"
            t.write_bytes(self.body)
            return t, {}
        fetch_inputs.download = stub

    def tearDown(self):
        fetch_inputs.RECORD, fetch_inputs.download, fetch_inputs.wanted = self.saved
        shutil.rmtree(self.tmp)

    def put(self, digest):
        self.rec.write_text(json.dumps({self.key: {"url": "u", "bytes": 5, "sha256": digest}}))

    def test_fetch_ok_then_skip(self):
        self.put(hashlib.sha256(self.body).hexdigest())
        self.assertEqual(fetch_inputs.fetch(into=self.tmp), 0)
        self.assertEqual((self.tmp / self.key).read_bytes(), self.body)
        self.body = b"changed"                                   # a second run must not download again
        self.assertEqual(fetch_inputs.fetch(into=self.tmp), 0)

    def test_sha_differs(self):
        self.put("0" * 64)
        self.assertEqual(fetch_inputs.fetch(into=self.tmp), 2)
        self.assertFalse((self.tmp / self.key).exists())
        self.assertEqual(list((self.tmp / self.key).parent.glob(".part-*")), [])

    def test_no_record(self):
        self.rec.write_text("{}")
        self.assertEqual(fetch_inputs.fetch(into=self.tmp), 3)


if __name__ == "__main__":
    unittest.main()
