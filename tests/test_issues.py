"""Step 11.3 (spec/scheduler.yaml issues_11_3): issue kinds and wording, the term freeze, an accepted revision,
de-dup keys, and posting through a stub gh. Runs on temp copies of the live bundle; never touches data/."""
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
import issues  # noqa: E402
import publish  # noqa: E402

V1 = json.loads((ROOT / "data" / "current.json").read_text())["bundle"]
D1 = ROOT / "raw/benchmarks/census-1yr/PUMS_Data_Dictionary_2024.csv"
D5 = ROOT / "raw/benchmarks/census-5yr/PUMS_Data_Dictionary_2020-2024.csv"
CAND = "test-candidate"
OFF_TERM, IN_TERM = dt.date(2026, 11, 1), dt.date(2027, 2, 1)


class Issues(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (D1.exists() and D5.exists()):
            raise unittest.SkipTest("frozen data dictionaries not in raw/benchmarks/")

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.data = self.tmp / "data"
        for bid in (V1, CAND):
            shutil.copytree(ROOT / "data" / "bundles" / V1, self.data / "bundles" / bid)
            m = self.manifest(bid)
            m.update(git_commit="a" * 40, worktree_dirty=False, bundle=bid)
            self.write_manifest(m, bid)
        (self.data / "current.json").write_text(json.dumps({"bundle": V1}))
        self.terms = self.tmp / "term.json"
        self.terms.write_text(json.dumps({"terms": [{"name": "Spring 2027", "start": "2027-01-12", "end": "2027-04-29"}]}))

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def manifest(self, bid=CAND):
        return json.loads((self.data / "bundles" / bid / "manifest.json").read_text())

    def write_manifest(self, m, bid=CAND):
        (self.data / "bundles" / bid / "manifest.json").write_text(json.dumps(m, indent=1, sort_keys=True))

    def run_publish(self, today=OFF_TERM, **kw):
        return publish.publish(self.data, CAND, str(D1), str(D5), today=today, terms_path=self.terms, **kw)

    def current(self):
        return json.loads((self.data / "current.json").read_text())["bundle"]

    def key(self, body):
        return issues.KEY_RE.search(body).group(1)

    # ---------- kinds and wording ----------
    def test_rebuild(self):
        code, name, body = self.run_publish()
        self.assertEqual((code, name), (0, "rebuild"))
        self.assertIn("No new Census data", body)
        self.assertNotIn("Draft announcement", body)
        self.assertEqual(self.key(body), f"publish:{CAND}")
        self.assertEqual(issues.title_of(body), f"Numbers rebuilt with the same Census data: {CAND}")

    def test_new_data(self):
        m = self.manifest()
        m["years"] = {"rank": "ACS 2025 1-year", "other": "ACS 2021-25 5-year"}
        self.write_manifest(m)
        code, name, body = self.run_publish()
        self.assertEqual((code, name), (0, "new-data"))
        self.assertIn("Draft announcement", body)
        self.assertIn("ACS 2025 1-year", body)
        self.assertEqual(self.current(), CAND)

    def test_term_freeze(self):
        code, name, body = self.run_publish(today=IN_TERM)
        self.assertEqual((code, name), (0, "ready"))
        self.assertEqual(self.current(), V1, "the term freeze must not flip current.json")
        self.assertIn("Spring 2027", body)
        self.assertEqual(self.key(body), f"ready:{CAND}")
        code, name, _ = self.run_publish(today=IN_TERM, publish_in_term=True)
        self.assertEqual((code, name), (0, "rebuild"))
        self.assertEqual(self.current(), CAND)

    def revised(self):
        """Candidate built from a revised 5-year zip; a probe that saw the change."""
        m = self.manifest()
        path = next(p for p in m["sources"] if "acs5" in p)
        new_sha = hashlib.sha256(b"revised").hexdigest()
        m["sources"][path] = new_sha
        self.write_manifest(m)
        src = json.loads((ROOT / "spec" / "sources.json").read_text())
        probe = {"sources": {sid: {"bytes": s["bytes"], "last_modified": s["last_modified"]} for sid, s in src.items()}}
        sid = Path(path).parent.name
        probe["sources"][sid]["last_modified"] = "Thu, 01 Apr 2027 12:00:00 GMT"
        p = self.tmp / "probe.json"
        p.write_text(json.dumps(probe))
        return sid, new_sha, str(p)

    def test_revision_holds_then_accepted(self):
        sid, new_sha, probe = self.revised()
        code, name, body = self.run_publish(probe=probe)
        self.assertEqual((code, name), (1, "revision"))
        self.assertTrue(self.key(body).startswith("revision:"))
        self.assertEqual(self.current(), V1)
        code, name, _ = self.run_publish(probe=probe, accept={sid: "0" * 64})
        self.assertEqual((code, name), (1, "revision"), "a wrong accepted sha must still hold")
        code, name, body = self.run_publish(probe=probe, accept={sid: new_sha})
        self.assertEqual((code, name), (0, "revision-published"))
        self.assertIn("Census revised", body)
        self.assertEqual(self.current(), CAND)

    def test_stale_key(self):
        stale, body = publish.stale(self.data, dt.date(2025, 12, 4), dt.date(2027, 6, 1))
        self.assertTrue(stale)
        self.assertEqual(self.key(body), f"stale:{V1}")

    def test_failure(self):
        body = publish.failure(self.data, "probe", "HEAD ... HTTP 503", "https://run", dt.date(2027, 3, 3))
        self.assertEqual(self.key(body), "failure:2027-03:probe")
        self.assertIn("Nothing changed on the page", body)
        self.assertEqual(issues.title_of(body), "The monthly data check failed: probe")

    # ---------- posting (stub gh; no network) ----------
    def gh_stub(self, existing):
        calls = []
        def gh(args):
            calls.append(args)
            if args[:2] == ["issue", "list"]:
                return json.dumps([{"number": i + 1, "title": "t", "body": b} for i, b in enumerate(existing)])
            if args[:2] == ["issue", "create"]:
                body = Path(args[args.index("--body-file") + 1]).read_text()
                existing.append(body)
                return "https://github.com/x/y/issues/9\n"
            raise AssertionError(args)
        return gh, calls

    def test_post_once_per_key(self):
        _, _, body = self.run_publish()
        gh, calls = self.gh_stub([])
        title = issues.title_of(body)
        self.assertEqual(issues.post(title, body, self.key(body), ["rebuild"], gh=gh), "https://github.com/x/y/issues/9")
        self.assertEqual(issues.post(title, body, self.key(body), ["rebuild"], gh=gh), "duplicate")
        creates = [c for c in calls if c[:2] == ["issue", "create"]]
        self.assertEqual(len(creates), 1)
        self.assertIn("data-bot", creates[0])

    def test_split_key(self):
        _, _, body = self.run_publish()
        b, k = issues.split_key(body)
        self.assertEqual(k, f"publish:{CAND}")
        self.assertNotIn("dashboard-key", b)

    def test_dry_run_title(self):
        gh, calls = self.gh_stub([])
        issues.post("New Census data published: x", "# t\n", "publish:x", [], gh=gh, dry_run=True)
        c = next(c for c in calls if c[:2] == ["issue", "create"])
        self.assertEqual(c[c.index("--title") + 1], "[DRY RUN] New Census data published: x")
        self.assertIn("dry-run", c)


if __name__ == "__main__":
    unittest.main()
