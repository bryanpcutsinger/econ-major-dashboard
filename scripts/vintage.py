"""The data vintage (spec/scheduler.yaml, 11.1): every path, file name, URL, bundle prefix, and manifest label the
builds use comes from spec/vintage.json, or from the file named by the DASHBOARD_VINTAGE environment variable.

    from vintage import V
    V.acs1_zip, V.cache, V.bundle_prefix, V.years, ...
"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CENSUS = "https://www2.census.gov/programs-surveys/acs"


class Vintage:
    def __init__(self, path=None):
        path = Path(path or os.environ.get("DASHBOARD_VINTAGE") or ROOT / "spec" / "vintage.json")
        c = json.loads(Path(path).read_text())
        self.source = path
        self.y1 = int(c["acs1"])
        self.a5, self.b5 = (int(x) for x in c["acs5"])
        assert self.b5 - self.a5 == 4, "the 5-year file spans five survey years"
        self.onet_release, self.onet_link = c["onet_release"], c["onet_link"]
        self.puma_vintage = int(c["puma_vintage"])
        y, a, b = self.y1, self.a5, self.b5
        # source ids = raw folder names (gates H9 keys on them)
        self.acs1_id, self.acs5_id = f"acs1-{y}", f"acs5-{a}-{b}"
        raw = ROOT / "raw"
        self.acs1_zip = raw / self.acs1_id / "csv_pus.zip"
        self.acs5_zip = raw / self.acs5_id / "csv_pus.zip"
        self.dict1 = raw / "benchmarks" / "census-1yr" / f"PUMS_Data_Dictionary_{y}.csv"
        self.dict5 = raw / "benchmarks" / "census-5yr" / f"PUMS_Data_Dictionary_{a}-{b}.csv"
        self.socp_codes = raw / "benchmarks" / "census-codelists" / f"SOCP-{y}.json"
        self.onet_zip = raw / "benchmarks" / "onet" / f"db_{self.onet_release}_text.zip"
        p = self.puma_vintage
        self.tract_puma = raw / "benchmarks" / "census-geo" / f"{p}_Census_Tract_to_{p}_PUMA.txt"
        self.cache = ROOT / "cache" / f"acs5-{a}-{b}-ba.parquet"
        self.cache_hs = ROOT / "cache" / f"acs5-{a}-{b}-hs.parquet"   # high school only (spec/lifetime-panel.yaml)
        panels = ROOT / "output" / "panels"
        self.rank_json, self.rank_csv = panels / f"rank-{y}.json", panels / f"rank-{y}.csv"
        self.rank_profile, self.compare_json = panels / f"rank-{y}-profile.json", panels / f"compare-{y}.json"
        self.bundle_prefix = f"{y}-1yr_{a}-{str(b)[2:]}-5yr_"
        self.years = {"rank": f"ACS {y} 1-year", "other": f"ACS {a}-{str(b)[2:]} 5-year"}
        self.dollar_year = y                    # ADJINC brings both files to the 1-year file's year (pairing rule)
        assert b == y, "pairing rule: the 5-year file ends in the 1-year file's year"
        # where each input comes from (spec/inputs.json records bytes and sha256)
        self.urls = {
            self.acs1_zip: f"{CENSUS}/data/pums/{y}/1-Year/csv_pus.zip",
            self.acs5_zip: f"{CENSUS}/data/pums/{b}/5-Year/csv_pus.zip",
            self.dict1: f"{CENSUS}/tech_docs/pums/data_dict/PUMS_Data_Dictionary_{y}.csv",
            self.dict5: f"{CENSUS}/tech_docs/pums/data_dict/PUMS_Data_Dictionary_{a}-{b}.csv",
            self.socp_codes: f"https://api.census.gov/data/{y}/acs/acs1/pums/variables/SOCP.json",
            self.onet_zip: f"https://www.onetcenter.org/dl_files/database/db_{self.onet_release}_text.zip",
            self.tract_puma: f"https://www2.census.gov/geo/docs/maps-data/data/rel{p}/{p}_Census_Tract_to_{p}_PUMA.txt",
        }
        self.pums = [self.acs1_zip, self.acs5_zip]


V = Vintage()
