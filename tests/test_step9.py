"""Step 9 done checks (spec/gates.yaml tests): each hard gate fails once on its test change and picks
its issue template; each warning fires once; rollback works both ways; the stale check; first publish.

Every test runs on a temp copy of bundle v1 (live) and a second copy (the candidate); the real data/
is never written. Needs the frozen data dictionaries in raw/benchmarks/ (H8).

Run from the repo root:  python3 -m unittest discover -s tests -v
"""
import datetime as dt
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import change_list  # noqa: E402
import gates  # noqa: E402
import publish  # noqa: E402

V1 = json.loads((ROOT / "data" / "current.json").read_text())["bundle"]
D1 = ROOT / "raw/benchmarks/census-1yr/PUMS_Data_Dictionary_2024.csv"
D5 = ROOT / "raw/benchmarks/census-5yr/PUMS_Data_Dictionary_2020-2024.csv"
CAND = "test-candidate"


class Step9(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not (D1.exists() and D5.exists()):
            raise unittest.SkipTest("frozen data dictionaries not in raw/benchmarks/")

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.data = self.tmp / "data"
        for bid in (V1, CAND):
            shutil.copytree(ROOT / "data" / "bundles" / V1, self.data / "bundles" / bid)
            # tests do not depend on the working tree: both copies get clean provenance
            m = self.get("manifest", bid)
            m.update(git_commit="a" * 40, worktree_dirty=False, bundle=bid)
            self.put("manifest", m, bid)
        (self.data / "current.json").write_text(json.dumps({"bundle": V1}))

    def tearDown(self):
        shutil.rmtree(self.tmp)

    # ---------- helpers ----------
    def path(self, name, bid=CAND):
        return self.data / "bundles" / bid / f"{name}.json"

    def get(self, name, bid=CAND):
        return json.loads(self.path(name, bid).read_text())

    def put(self, name, obj, bid=CAND, resign=True):
        self.path(name, bid).write_text(json.dumps(obj, indent=1, sort_keys=True))
        if resign and name != "manifest":
            m = self.get("manifest", bid)
            m["files"][f"{name}.json"] = hashlib.sha256(self.path(name, bid).read_bytes()).hexdigest()
            self.put("manifest", m, bid)

    def failed(self, d5=D5, probe=None):
        rep = gates.run(self.data, CAND, None, str(D1), str(d5) if d5 else None, probe)
        return {g for g, v in rep["gates"].items() if not v["ok"]}

    def current(self):
        return json.loads((self.data / "current.json").read_text())

    def assert_held(self, gate, template="gate-hold", d5=D5, probe=None):
        self.assertEqual(self.failed(d5, probe), {gate})
        before = self.current()
        code, name, body = publish.publish(self.data, CAND, str(D1), str(d5) if d5 else None, probe)
        self.assertEqual((code, name), (1, template))
        self.assertIn(gate, body)
        self.assertEqual(self.current(), before, "a held publish must not touch current.json")

    def publish_ok(self):
        code, name, body = publish.publish(self.data, CAND, str(D1), str(D5))
        self.assertEqual((code, name), (0, "new-data"), body)
        return body

    def warnings(self):
        return change_list.build(self.data, CAND, V1)["warnings"]

    # ---------- clean ----------
    def test_clean_candidate_passes(self):
        self.assertEqual(self.failed(), set())
        self.publish_ok()
        self.assertEqual(self.current(), {"bundle": CAND, "previous": V1})
        self.assertEqual({k: len(v) for k, v in self.warnings().items()}, {f"W{i}": 0 for i in range(1, 7)})

    def test_already_live(self):
        code, name, msg = publish.publish(self.data, V1, str(D1), str(D5))
        self.assertEqual((code, name), (0, None))
        self.assertIn("already live", msg)

    def test_first_publish(self):
        (self.data / "current.json").unlink()
        rep = gates.run(self.data, CAND, None, str(D1), str(D5))
        self.assertTrue(rep["passed"])
        self.assertIn("first bundle with stats", rep["gates"]["H7_sample_size"]["notes"])
        body = self.publish_ok()
        self.assertIn("First bundle", body)
        self.assertEqual(self.current(), {"bundle": CAND, "previous": None})

    # ---------- hard gates ----------
    def test_H1_byte_change(self):
        with open(self.path("local"), "a") as fh:
            fh.write("\n")                                   # valid JSON, sha no longer the manifest's
        self.assert_held("H1_outputs")

    def test_H1_microdata_key(self):
        c = self.get("codes")
        c["SERIALNO"] = ["2024HU0000001"]
        self.put("codes", c)
        self.assert_held("H1_outputs")

    def test_H2_unmapped_code(self):
        m = self.get("manifest")
        m["gates"]["indp_unmapped"] = [9999]
        self.put("manifest", m)
        self.assert_held("H2_codes_mapped")

    def test_H3_major_missing(self):
        so = self.get("same_occupation")
        del so["grad=0"]["Accounting"]
        self.put("same_occupation", so)
        self.assert_held("H3_majors_present")

    def test_H4_puma_list(self):
        c = self.get("codes")
        c["south_florida_pumas"] = c["south_florida_pumas"][1:]
        self.put("codes", c)
        self.assert_held("H4_south_florida")

    def test_H5_cell_rule(self):
        lo = self.get("local")
        cell = lo["grad=0|fulltime=1"]["florida"]["economics"]
        self.assertFalse(cell["hidden"])
        cell["n"] = 50
        self.put("local", lo)
        self.assert_held("H5_cell_rules")

    def test_H6_label(self):
        so = self.get("same_occupation")
        for r in so["grad=0"]["Nursing"]["major_top"]["rows"]:
            dd = r["econ_vs_major"]
            if dd.get("label") == "about the same" and abs(dd["d"]) < dd["moe"] - 1:
                dd["label"] = "better"
                break
        else:
            self.fail("no 'about the same' row to flip")
        self.put("same_occupation", so)
        self.assert_held("H6_labels")

    def test_H7_sample_size(self):
        m = self.get("manifest")
        m["stats"]["acs5"]["records_kept"] = int(m["stats"]["acs5"]["records_kept"] * 1.10)
        self.put("manifest", m)
        self.assert_held("H7_sample_size")

    def test_H8_dictionary_changed(self):
        lines = D5.read_text(encoding="utf-8-sig").splitlines(keepends=True)
        drop = next(i for i, ln in enumerate(lines) if ln.startswith('VAL,SCHL,C,2,"24"'))
        bad = self.tmp / "dictionary.csv"
        bad.write_text("".join(lines[:drop] + lines[drop + 1:]), encoding="utf-8")
        self.assert_held("H8_dictionary", d5=bad)

    def test_H8_dictionary_missing(self):
        self.assert_held("H8_dictionary", d5=None)

    def test_H9_revision(self):
        src = json.loads((ROOT / "spec" / "sources.json").read_text())
        probe = {"sources": {sid: {"bytes": s["bytes"], "last_modified": s["last_modified"]} for sid, s in src.items()}}
        p = self.tmp / "probe.json"
        p.write_text(json.dumps(probe))
        self.assertEqual(self.failed(probe=str(p)), set(), "an unchanged probe must pass")
        probe["sources"]["acs5-2020-2024"]["last_modified"] = "Thu, 01 Apr 2027 12:00:00 GMT"
        p.write_text(json.dumps(probe))
        self.assert_held("H9_source_revision", template="revision", probe=str(p))

    def test_H10_provenance(self):
        m = self.get("manifest")
        m["worktree_dirty"] = True
        self.put("manifest", m)
        self.assert_held("H10_provenance")

    # ---------- warnings (publish still succeeds) ----------
    def test_W1_economics_pay(self):
        lo = self.get("local")
        lo["grad=0|fulltime=1"]["florida"]["economics"]["median"] *= 1.2
        self.put("local", lo)
        self.assertTrue(self.warnings()["W1"])
        self.assertIn("W1 economics pay moved > 8%: 1", self.publish_ok())

    def test_W1_counts_each_economics_cell_once(self):
        so = self.get("same_occupation")
        hits = 0
        for v in so["grad=0"].values():                      # the economics cell for one job, in every list
            for which in ("major_top", "economics_top"):
                for r in v[which]["rows"]:
                    if r["occp"] == 800 and not r["economics"]["hidden"]:
                        r["economics"]["median"] *= 1.2
                        hits += 1
        self.assertGreater(hits, 1)
        self.put("same_occupation", so)
        self.assertEqual(len(self.warnings()["W1"]), 1)

    def test_W2_major_pay(self):
        r = self.get("rank")
        row = next(x for x in r["measures"]["pay_mid|grad=0|fulltime=1"] if x["major"] == "Accounting")
        row["estimate"] *= 1.3
        self.put("rank", r)
        self.assertEqual(len(self.warnings()["W2"]), 1)
        self.publish_ok()

    def test_W3_rate(self):
        r = self.get("rank")
        row = next(x for x in r["measures"]["unemployment"] if x["major"] == "Accounting")
        row["estimate"] += 3
        self.put("rank", r)
        self.assertEqual(len(self.warnings()["W3"]), 1)
        self.publish_ok()

    def test_W4_economics_rank(self):
        r = self.get("rank")
        next(x for x in r["measures"]["pay_mid|grad=0|fulltime=1"] if x["major"] == "Economics")["rank"] += 6
        self.put("rank", r)
        self.assertEqual(len(self.warnings()["W4"]), 1)
        self.publish_ok()

    def test_W5_two_step_label(self):
        so = self.get("same_occupation")
        t = so["grad=0"]["Nursing"]["major_top"]
        row = next(r for r in t["rows"] if r["econ_vs_major"].get("label") == "better")
        row["econ_vs_major"]["d"] *= -1                       # consistent with the rule, so H6 passes
        row["econ_vs_major"]["label"] = "worse"
        t["headline"]["better"] -= 1
        t["headline"]["worse"] += 1
        self.put("same_occupation", so)
        self.assertEqual(self.failed(), set())
        self.assertEqual(len(self.warnings()["W5"]), 1)
        self.publish_ok()

    def test_W6_hidden(self):
        r = self.get("rank")
        rows = [x for x in r["measures"]["pay_mid|grad=0|fulltime=1"] if x["major"] != "Economics" and not x["hidden"]]
        for x in rows[:20]:
            x["n"], x["hidden"] = 50, True                    # consistent with D5, so H5 passes
        self.put("rank", r)
        self.assertEqual(self.failed(), set())
        self.assertEqual([w["panel"] for w in self.warnings()["W6"]], ["rank|pay_mid|grad=0|fulltime=1"])
        self.publish_ok()

    # ---------- rollback, stale, pin ----------
    def test_rollback(self):
        self.assertEqual(publish.rollback(self.data)[0], 1, "no previous yet")
        self.assertEqual(self.current(), {"bundle": V1})
        self.publish_ok()
        code, _, msg = publish.rollback(self.data)
        self.assertEqual(code, 0, msg)
        self.assertEqual(self.current(), {"bundle": V1, "previous": None})
        self.assertEqual(publish.rollback(self.data)[0], 1, "second rollback: nothing before v1")
        self.assertEqual(self.current()["bundle"], V1)
        hist = json.loads((self.data / "history.json").read_text())
        self.assertEqual([h["action"] for h in hist], ["publish", "rollback"])

    def test_stale(self):
        pub = dt.date(2025, 12, 4)
        is_stale, body = publish.stale(self.data, pub, dt.date(2027, 4, 5))
        self.assertTrue(is_stale)
        self.assertIn("16 months", body)
        self.assertFalse(publish.stale(self.data, pub, dt.date(2027, 2, 5))[0])

    def test_no_lecture_pin(self):
        self.assertEqual(change_list.build(self.data, CAND, V1)["pin"], "no lecture pin")


if __name__ == "__main__":
    unittest.main()
