"""Step 11.2 probe (spec/scheduler.yaml probe_11_2): is there a new or revised ACS vintage?

    python3 scripts/probe.py [--out probe.json] [--fixture fixture.json] [--data data]

Checks the live bundle's sources (HEAD each zip, hash each data dictionary) and the vintage one year on (HEAD both
zips and both dictionaries; the Census API pums.json as a second signal). Writes one JSON with a decision:
error > revision_suspect > new_vintage > pending > nothing. Exit 1 only for error. Standard library only, no key.
"""
import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from vintage import V  # noqa: E402

UA = {"User-Agent": "econ-major-dashboard probe (github.com/bryanpcutsinger/econ-major-dashboard)"}
MIN_ZIP = 10 * 1024 * 1024          # a zip counts as present only above 10 MB (an error page is small)
RETRIES, PAUSE, TIMEOUT = 2, 3, 60


class ProbeError(Exception):
    pass


class Web:
    """Real requests. Returns (status, headers, body); 4xx other than 403/429 is a normal answer."""

    def request(self, method, url):
        last = None
        for attempt in range(RETRIES + 1):
            try:
                req = urllib.request.Request(url, method=method, headers=UA)
                with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                    return r.status, {k.lower(): v for k, v in r.headers.items()}, (r.read() if method == "GET" else b"")
            except urllib.error.HTTPError as e:
                if e.code in (403, 429) or e.code >= 500:
                    last = f"{method} {url}: HTTP {e.code}"
                else:
                    return e.code, {k.lower(): v for k, v in e.headers.items()}, b""
            except Exception as e:                       # timeout, DNS, connection reset, ...
                last = f"{method} {url}: {type(e).__name__}: {e}"
            if attempt < RETRIES:
                time.sleep(PAUSE)
        raise ProbeError(last)


class Fixture(Web):
    """Recorded answers for tests and the dry run: {url: {status, headers, body | body_sha256}}; HEAD and GET share one."""

    def __init__(self, path_or_dict):
        self.map = path_or_dict if isinstance(path_or_dict, dict) else json.loads(Path(path_or_dict).read_text())

    def request(self, method, url):
        r = self.map.get(url)
        if r is None:
            raise ProbeError(f"{method} {url}: fixture has no answer (connection error)")
        status = r.get("status", 200)
        if status in (403, 429) or status >= 500:
            raise ProbeError(f"{method} {url}: HTTP {status}")
        body = r.get("body", "").encode()
        return status, {k.lower(): v for k, v in r.get("headers", {}).items()}, body if method == "GET" else b""

    def body_sha(self, url, body):
        return self.map.get(url, {}).get("body_sha256") or hashlib.sha256(body).hexdigest()


def live_records(data):
    """The live bundle id and, per source id, the record to compare: manifest source_records, else spec/sources.json."""
    cur = json.loads((Path(data) / "current.json").read_text())["bundle"]
    m = json.loads((Path(data) / "bundles" / cur / "manifest.json").read_text())
    stored = json.loads((ROOT / "spec" / "sources.json").read_text())
    recs = {}
    for path in m.get("sources", {}):
        sid = Path(path).parent.name
        r = (m.get("source_records") or {}).get(sid) or stored.get(sid)
        if r is None:
            raise ProbeError(f"{sid}: no source record in the manifest or spec/sources.json")
        recs[sid] = {"url": r["url"], "bytes": r["bytes"], "last_modified": r["last_modified"], "sha256": r["sha256"],
                     "dictionary": r["dictionary"]}
    return cur, recs


def confirmed(data):
    """Fingerprints confirmed by a same-sha download (data/last-checked.json 'confirmed'; written in 11.5 / 11.7)."""
    p = Path(data) / "last-checked.json"
    try:
        return json.loads(p.read_text()).get("confirmed", {})
    except (OSError, ValueError):
        return {}


def probe(web, data=ROOT / "data", now=None, next_offset=1):
    out = {"version": 1, "probed_at": now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "vintage": V.config, "sources": {}, "next": {}, "api": {}, "reasons": [], "errors": []}
    sha_of = getattr(web, "body_sha", lambda url, body: hashlib.sha256(body).hexdigest())

    def call(method, url):
        try:
            return web.request(method, url)
        except ProbeError as e:
            out["errors"].append(str(e))
            return None

    try:
        out["live_bundle"], recs = live_records(data)
    except (OSError, ValueError, KeyError, ProbeError) as e:
        out["errors"].append(f"live bundle: {e}")
        recs = {}
    conf = confirmed(data)
    suspect = False

    # 1. live sources: zip HEAD + dictionary hash
    for sid, r in recs.items():
        rec = {"url": r["url"], "bytes": None, "last_modified": None, "sha256": None,
               "dictionary_sha256": None, "dictionary_changed": None}
        out["sources"][sid] = rec
        got = call("HEAD", r["url"])
        if got:
            status, h, _ = got
            if status != 200 or "content-length" not in h or "last-modified" not in h:
                out["errors"].append(f"HEAD {r['url']}: status {status}, headers {sorted(h)} (want 200 with "
                                     "Content-Length and Last-Modified)")
            else:
                rec["bytes"], rec["last_modified"] = int(h["content-length"]), h["last-modified"]
                c = conf.get(sid)
                if (rec["bytes"], rec["last_modified"]) == (r["bytes"], r["last_modified"]):
                    rec["sha256"] = None                 # unchanged; H9 compares bytes and Last-Modified
                elif c and (rec["bytes"], rec["last_modified"]) == (c["bytes"], c["last_modified"]):
                    rec["sha256"] = c["sha256"]          # a re-upload already confirmed by sha: H9's sha branch
                    out["reasons"].append(f"{sid}: new Last-Modified, confirmed earlier as a re-upload (same sha256)")
                else:
                    suspect = True
                    out["reasons"].append(f"{sid}: zip changed: bytes {r['bytes']} -> {rec['bytes']}, Last-Modified "
                                          f"{r['last_modified']!r} -> {rec['last_modified']!r}")
        d = r["dictionary"]
        got = call("GET", d["url"])
        if got:
            status, _, body = got
            if status != 200:
                out["errors"].append(f"GET {d['url']}: status {status}")
            else:
                rec["dictionary_sha256"] = sha_of(d["url"], body)
                rec["dictionary_changed"] = rec["dictionary_sha256"] != d["sha256"]
                if rec["dictionary_changed"]:
                    suspect = True
                    out["reasons"].append(f"{sid}: data dictionary changed (sha256 {d['sha256'][:12]} -> "
                                          f"{rec['dictionary_sha256'][:12]})")

    # 2. the vintage one year on (pairing rule: both files, both dictionaries)
    nv = V.shifted(next_offset)         # 1 = next year; 0 = the dry run's forced 'new vintage' (dry_run_11_8)
    names = {nv.acs1_id: nv.acs1_zip, nv.acs5_id: nv.acs5_zip,
             f"dictionary-{nv.acs1_id}": nv.dict1, f"dictionary-{nv.acs5_id}": nv.dict5}
    present = {}
    for name, path in names.items():
        url = nv.urls[path]
        got = call("HEAD", url)
        rec = {"url": url, "status": None, "bytes": None, "last_modified": None}
        out["next"][name] = rec
        if got:
            status, h, _ = got
            rec["status"] = status
            rec["bytes"] = int(h["content-length"]) if "content-length" in h else None
            rec["last_modified"] = h.get("last-modified")
            big = name.startswith("dictionary-") or (rec["bytes"] or 0) > MIN_ZIP
            present[name] = status == 200 and big
            if status == 200 and not big:
                out["reasons"].append(f"{name}: status 200 but only {rec['bytes']} bytes: not counted as present")
    for prod in ("acs1", "acs5"):
        url = f"https://api.census.gov/data/{nv.y1}/acs/{prod}/pums.json"
        got = call("GET", url)
        out["api"][f"{prod}-{nv.y1}"] = {"url": url, "status": got[0] if got else None}

    # 3. decision
    n_present = sum(present.values())
    if out["errors"]:
        decision = "error"
    elif suspect:
        decision = "revision_suspect"
    elif present and n_present == len(names):
        decision = "new_vintage"
        out["reasons"].append(f"{nv.acs1_id} and {nv.acs5_id}: both zips and both dictionaries are out")
    elif n_present:
        decision = "pending"
        out["reasons"].append("out so far: " + ", ".join(k for k, v in present.items() if v))
    else:
        decision = "nothing"
    if decision != "error":
        for k, a in out["api"].items():
            on_web = any(v for n, v in present.items() if n.startswith(k.split("-")[0] + "-"))
            if (a["status"] == 200) != on_web:
                out["reasons"].append(f"note: Census API {k} status {a['status']}, zip on the web: {on_web}")
    out["decision"] = decision
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="-")
    ap.add_argument("--fixture")
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--next-offset", type=int, default=1, help="0 in the dry run only")
    a = ap.parse_args(argv)
    res = probe(Fixture(a.fixture) if a.fixture else Web(), a.data, next_offset=a.next_offset)
    text = json.dumps(res, indent=1, sort_keys=True) + "\n"
    if a.out == "-":
        sys.stdout.write(text)
    else:
        Path(a.out).write_text(text)
        print(f"{res['decision']}: " + "; ".join(res["reasons"] + res["errors"]) if res["reasons"] or res["errors"]
              else res["decision"])
    return 1 if res["decision"] == "error" else 0


if __name__ == "__main__":
    sys.exit(main())
