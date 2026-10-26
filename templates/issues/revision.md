# Census changed a file we already publish

The probe found a change in a source file that the live bundle `$live` uses. Census may have
revised the data. **Nothing changed on the page.**

## Changed sources

$failed

## What to do

1. Read the Census release notes for this file.
2. Download the new file, update `spec/sources.json` (`python3 scripts/make_baselines.py`), and
   rebuild. The rebuild goes through every gate and opens its own issue.
3. Record the revision in `spec/exception-ledger.md`.
