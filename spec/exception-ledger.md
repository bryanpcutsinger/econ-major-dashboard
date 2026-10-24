# Exception ledger

Every conflict inside a source, every judgment call, and every benchmark cell that fails is
logged here with a date. A failed cell stays failed until an entry explains it. Tolerances
are never widened after results are seen.

## Known before any data was loaded (2026-10-24)

| # | Item | Source | Status / plan |
|---|---|---|---|
| E1 | Weeks rule: text says "40 or more weeks"; table notes say "more than 40" | HC p. 327 vs. Tables 1–3 notes | Variant in `rate-grid.yaml`. With exact weeks (WKWN, 2019+) the two differ only at 40 weeks. 2018 has only interval weeks (WKW), so ">40" cannot be applied exactly there |
| E2 | Sample size: fn. 6 says 74,273 mid-career economics majors; Table 1 implies about 8,770; Table 3 shows 4,820 | HC fn. 6, Tables 1, 3 | Probably different filters (fn. 6 = before the work filters?). Test: count economics, ages 35–45, before and after each filter |
| E3a | Table 1 names carry footnote letters ("servicesa", "assistantsb") | `hc-2026/table1.csv` | Match occupations by OCCP code, or strip the trailing footnote letter |
| E3 | Table 3 note says "who majored in economics" but the table covers all 73 majors | HC Table 3 note | Copy error in the note; treat Table 3 as all majors |
| E4 | Dollar rule: Table 3 repeats medians that imply three year factors (0.98296; ≈1.0225; ≈1.042) | HC Table 3 (claude-leg arithmetic) | Variants `dollars` in the grid |
| E5 | "186 majors" in the paper; Census FOD1P lists 173–175 codes per year (175 distinct across 2018–24, plus "N") | HC p. 327; frozen code lists | 186 may count IPUMS DEGFIELDD detail. Our map uses FOD1P; check counts in Table 3 |
| E6 | 89 of 175 code assignments in `major73.csv` are our judgment (`basis = judgment`) | `scripts/build_major73.py` | Test against HC Table 3 unweighted counts (exact). Misses concentrated in judgment rows → mapping; misses in name rows → sample rules |
| E7 | Codes that appear or vanish: 1099 and 3201 (2018–19 only); 1107 and 4009 (2023+) | frozen code lists | 4009 (Data Science) mapped to Business Analytics; 6212 also mapped there, because HC Table 3 (2021–23) has Business Analytics before 4009 existed |
| E8 | NY Fed April 2024 posting: only one Wayback CSV capture (2024-05-07); HC cite the 2024-04-04 page | Wayback; HC fn. 9 | **VERIFIED 2026-10-24:** the same capture's chart-meta.json says "February 22, 2024 … Figures are for 2022", so this is the posting HC matched. The file is stored gzip-compressed, as served: gunzip before reading; its sha256 is of the compressed bytes |
| E9 | NY Fed by-major release date is Feb 4, 2026 (the data plan said Aug 6, 2026, the page date) | NYF24 chart-meta.json | Fix the plan text |
| E10 | HC acknowledge that Abel and Deitz shared "data, and code"; HC replicated wages in R | HC acknowledgments, p. 329 | If wages miss, the OpenICPSR package (fallback) should hold that logic |

## Found in session 1 (2026-10-24)

| # | Item | Source | Status / plan |
|---|---|---|---|
| E11 | The bulk CSV names the state column `STATE`; the API calls it `ST` | `psam_p12.csv` header | Use `STATE` in file code; the crosswalk row is fixed |
| E12 | Census key: metadata calls (`variables.json`) return 200 with no key; a data query with no key is redirected (302) | curl, 2026-10-24 | The probe uses metadata and the build uses bulk files, so **no key is needed** |
| E13 | 2025 1-year and 5-year PUMS metadata return 404 | curl, 2026-10-24 | Spring baseline stays 2024 1-year + 2020–24 5-year |
| E14 | ADJINC for 2024 = 1.015250 | `ADJINC-2024.json` | Raw vs adjusted wages differ by 1.5%; the NY Fed check decides which one matches |
| E15 | Weeks: in 2024 the variable is WKWN (exact weeks, 1–52) | `WKWN-2024.json` | E1 variants apply exactly from 2019 on |
