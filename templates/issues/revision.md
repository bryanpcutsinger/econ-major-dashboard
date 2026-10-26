# Census changed a file we already publish

The probe found a change in a source file that the live bundle `$live` uses. Census may have
revised the data. **Nothing changed on the page.**

## Changed sources

$failed

## What to do

1. Read the Census release notes for this file.
2. Compare the candidate's change list with the live numbers. Census revisions hold until you accept
   them (ruling 2026-10-26).
3. To accept: run the workflow by hand with **accept revision** set to `source id=new sha256`, or run
   `python3 scripts/publish.py <candidate> --accept-revision SID=SHA256` with the two dictionaries.
   Every other gate still runs.
4. Record the revision in `spec/exception-ledger.md`.
