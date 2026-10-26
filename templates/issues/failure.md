# The monthly data check failed: $step

The run on $date could not finish the step "$step". **Nothing changed on the page.** The live bundle
stays `$live`.

## What happened

$details

## What to do

1. Open the workflow run: $run_url
2. If Census or GitHub was down, the next monthly run tries again; nothing else is needed.
3. If the same step fails two months in a row, fix the cause and record it in `spec/exception-ledger.md`.
