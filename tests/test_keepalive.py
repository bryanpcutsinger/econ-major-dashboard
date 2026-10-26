"""Step 11.5 keep-alive (spec/scheduler.yaml workflow_11_5): data/last-checked.json from one probe run."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import keepalive  # noqa: E402


class KeepAlive(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "current.json").write_text(json.dumps({"bundle": "B"}))
        self.probe = self.tmp / "probe.json"

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_ka(self, probe, now):
        if probe is None:
            path = None
        else:
            self.probe.write_text(probe if isinstance(probe, str) else json.dumps(probe))
            path = self.probe
        return keepalive.keepalive(path, "u", self.tmp, now)

    def test_success_then_error_keeps_last_success(self):
        r = self.run_ka({"decision": "nothing", "reasons": [], "errors": []}, "2026-11-03T13:17:00Z")
        self.assertEqual((r["decision"], r["last_success"], r["live"]), ("nothing", "2026-11-03T13:17:00Z", "B"))
        r = self.run_ka({"decision": "error", "errors": ["HTTP 503"]}, "2026-12-03T13:17:00Z")
        self.assertEqual((r["decision"], r["last_success"], r["last_attempt"]),
                         ("error", "2026-11-03T13:17:00Z", "2026-12-03T13:17:00Z"))

    def test_bad_probe_output_is_error(self):
        for bad in (None, "not json", {"no": "decision"}):
            r = self.run_ka(bad, "2026-11-03T13:17:00Z")
            self.assertEqual(r["decision"], "error")
            self.assertIsNone(r["last_success"])

    def test_confirmed_carried(self):
        (self.tmp / "last-checked.json").write_text(json.dumps({"confirmed": {"acs5-2020-2024": {"sha256": "x"}},
                                                                "last_success": "2026-10-01T00:00:00Z"}))
        r = self.run_ka({"decision": "pending"}, "2026-11-03T13:17:00Z")
        self.assertEqual(r["confirmed"], {"acs5-2020-2024": {"sha256": "x"}})


if __name__ == "__main__":
    unittest.main()
