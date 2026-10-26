"""Step 11.2 probe (spec/scheduler.yaml probe_11_2): each decision from recorded answers (no network), and H9 on the
probe's output. The live bundle is read from data/ (read only); a temp data copy holds last-checked.json."""
import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import gates  # noqa: E402
import probe  # noqa: E402
from vintage import V  # noqa: E402

BIG = str(600 * 1024 * 1024)


class Probe(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        live = json.loads((ROOT / "data" / "current.json").read_text())["bundle"]
        (self.tmp / "bundles" / live).mkdir(parents=True)
        shutil.copy(ROOT / "data" / "current.json", self.tmp / "current.json")
        shutil.copy(ROOT / "data" / "bundles" / live / "manifest.json", self.tmp / "bundles" / live / "manifest.json")
        _, recs = probe.live_records(self.tmp)
        self.recs = recs
        fx = {}
        for sid, r in recs.items():                      # live: unchanged
            fx[r["url"]] = {"headers": {"Content-Length": str(r["bytes"]), "Last-Modified": r["last_modified"]}}
            fx[r["dictionary"]["url"]] = {"body": "x", "body_sha256": r["dictionary"]["sha256"]}
        nv = V.shifted(1)
        for path in (nv.acs1_zip, nv.acs5_zip, nv.dict1, nv.dict5):   # next: not out
            fx[nv.urls[path]] = {"status": 404}
        for prod in ("acs1", "acs5"):
            fx[f"https://api.census.gov/data/{nv.y1}/acs/{prod}/pums.json"] = {"status": 404}
        self.fx, self.nv = fx, nv

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_probe(self, fx=None):
        return probe.probe(probe.Fixture(copy.deepcopy(fx or self.fx)), self.tmp, now="2026-10-26T00:00:00Z")

    def out_next(self, fx, path, big=True):
        fx[self.nv.urls[path]] = {"headers": {"Content-Length": BIG if big else "512", "Last-Modified": "Thu, 03 Dec 2026 12:00:00 GMT"}}

    def h9(self, res):
        p = self.tmp / "probe.json"
        p.write_text(json.dumps(res))
        return gates.h9_source_revision(str(p), gates.load_bundle(self.tmp, json.loads((self.tmp / "current.json").read_text())["bundle"]))[0]

    def test_nothing(self):
        r = self.run_probe()
        self.assertEqual(r["decision"], "nothing", r)
        self.assertEqual(sorted(r["sources"]), sorted(self.recs))
        self.assertEqual(self.h9(r), [])

    def test_pending(self):
        fx = copy.deepcopy(self.fx)
        self.out_next(fx, self.nv.acs1_zip)
        self.assertEqual(self.run_probe(fx)["decision"], "pending")

    def test_new_vintage(self):
        fx = copy.deepcopy(self.fx)
        for p in (self.nv.acs1_zip, self.nv.acs5_zip):
            self.out_next(fx, p)
        for p in (self.nv.dict1, self.nv.dict5):
            fx[self.nv.urls[p]] = {"headers": {"Content-Length": "330000"}}
        self.assertEqual(self.run_probe(fx)["decision"], "new_vintage")

    def test_small_200_is_not_present(self):
        fx = copy.deepcopy(self.fx)
        self.out_next(fx, self.nv.acs1_zip, big=False)
        r = self.run_probe(fx)
        self.assertEqual(r["decision"], "nothing")
        self.assertTrue(any("not counted" in x for x in r["reasons"]))

    def test_revision_suspect_and_h9_holds(self):
        fx = copy.deepcopy(self.fx)
        sid = V.acs5_id
        fx[self.recs[sid]["url"]]["headers"]["Last-Modified"] = "Thu, 01 Apr 2027 12:00:00 GMT"
        r = self.run_probe(fx)
        self.assertEqual(r["decision"], "revision_suspect")
        self.assertEqual(len(self.h9(r)), 1)

    def test_dictionary_changed(self):
        fx = copy.deepcopy(self.fx)
        fx[self.recs[V.acs1_id]["dictionary"]["url"]]["body_sha256"] = "f" * 64
        r = self.run_probe(fx)
        self.assertEqual(r["decision"], "revision_suspect")
        self.assertTrue(r["sources"][V.acs1_id]["dictionary_changed"])

    def test_confirmed_reupload(self):
        fx = copy.deepcopy(self.fx)
        sid, new_lm = V.acs5_id, "Thu, 01 Apr 2027 12:00:00 GMT"
        fx[self.recs[sid]["url"]]["headers"]["Last-Modified"] = new_lm
        (self.tmp / "last-checked.json").write_text(json.dumps({"confirmed": {sid: {
            "bytes": self.recs[sid]["bytes"], "last_modified": new_lm, "sha256": self.recs[sid]["sha256"]}}}))
        r = self.run_probe(fx)
        self.assertEqual(r["decision"], "nothing", r["reasons"])
        self.assertEqual(r["sources"][sid]["sha256"], self.recs[sid]["sha256"])
        self.assertEqual(self.h9(r), [], "a confirmed re-upload takes H9's sha branch and passes")

    def test_errors(self):
        cases = []
        fx = copy.deepcopy(self.fx); fx[self.recs[V.acs1_id]["url"]] = {"status": 503}; cases.append(fx)
        fx = copy.deepcopy(self.fx); fx[self.nv.urls[self.nv.acs5_zip]] = {"status": 500}; cases.append(fx)
        fx = copy.deepcopy(self.fx); del fx[self.recs[V.acs1_id]["url"]]["headers"]["Last-Modified"]; cases.append(fx)
        fx = copy.deepcopy(self.fx); del fx[self.recs[V.acs5_id]["dictionary"]["url"]]; cases.append(fx)
        fx = copy.deepcopy(self.fx); fx[self.nv.urls[self.nv.acs1_zip]] = {"status": 429}; cases.append(fx)
        for i, fx in enumerate(cases):
            r = self.run_probe(fx)
            self.assertEqual(r["decision"], "error", f"case {i}: {r['reasons']}")
            self.assertTrue(r["errors"])


if __name__ == "__main__":
    unittest.main()
