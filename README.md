# Explore your major, next to economics

A self-updating dashboard for ECO 2023 (Principles of Microeconomics, FAU): how a
student's intended major compares with economics and with all majors, using Census
American Community Survey (ACS) microdata. "Our calculations from the ACS, following
[source]'s method": the NY Fed's *Labor Market for Recent College Graduates* and
Holian and Chiu (2026).

**Status:** session 1 (October 2026). Benchmarks frozen, spec written, Florida pilot passes.
Not yet built or published.

## Layout

- `scripts/` — `freeze_benchmarks.py` (download + hash benchmark files),
  `extract_hc_tables.py` (Holian and Chiu Tables 1–3 from the PDF),
  `build_major73.py` (degree codes → the NY Fed's 73 majors), `pilot_florida.py`.
- `spec/` — `benchmarks.yaml` (every sample rule with its source), `rate-grid.yaml`
  (variants declared before any national data), `exception-ledger.md`, `major73.csv`.
- `output/` — aggregate results only.
- `raw/` — downloaded files. **Gitignored: no microdata is ever committed or published.**

The project plan lives in the instructor's private course repo.
